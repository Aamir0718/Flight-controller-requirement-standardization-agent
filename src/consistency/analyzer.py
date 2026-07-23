"""Consistency analyzer for detecting duplicate, similar, and contradictory requirements.

Uses sentence embeddings for semantic similarity and local LLM for contradiction detection.
Falls back to TF-IDF if sentence-transformers is blocked by system security policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import get_settings
from llm.local_llm_client import LocalLLMClient

# Lazy import sentence-transformers (may be blocked by Windows Application Control)
_sentence_transformers_available = False
try:
    from sentence_transformers import SentenceTransformer
    _sentence_transformers_available = True
except (ImportError, OSError):
    # sentence-transformers or PyTorch not available (blocked by security policy)
    pass


class RelationshipType(Enum):
    """Types of relationships between requirements."""
    DUPLICATE = "duplicate"
    SIMILAR = "similar"
    CONTRADICTION = "contradiction"
    INDEPENDENT = "independent"


@dataclass(frozen=True)
class RequirementRelationship:
    """Represents a relationship between two requirements."""
    req_id_1: int
    req_id_2: int
    relationship_type: RelationshipType
    similarity_score: float
    confidence: float
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "req_id_1": self.req_id_1,
            "req_id_2": self.req_id_2,
            "relationship_type": self.relationship_type.value,
            "similarity_score": self.similarity_score,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ConsistencyResult:
    """Result of consistency analysis for a run."""
    run_id: int
    total_requirements: int
    relationships: list[RequirementRelationship]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_requirements": self.total_requirements,
            "relationships": [r.to_dict() for r in self.relationships],
            "summary": self.summary,
        }


class ConsistencyAnalyzer:
    """Analyzes requirement consistency using embeddings and LLM verification.
    
    Falls back to TF-IDF similarity if sentence-transformers is unavailable.
    """

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or get_settings()
        self.consistency_config = self.settings.get("consistency", {})
        
        self.duplicate_threshold = self.consistency_config.get(
            "duplicate_threshold", 0.95
        )
        self.similarity_threshold = self.consistency_config.get(
            "similarity_threshold", 0.80
        )
        self.enable_contradiction_check = self.consistency_config.get(
            "enable_contradiction_check", True
        )
        
        self.embedding_model_name = self.consistency_config.get(
            "embedding_model", "all-MiniLM-L6-v2"
        )
        
        # Check if sentence-transformers is available
        self.use_sentence_transformers = _sentence_transformers_available
        
        # Lazy load embedding model or TF-IDF vectorizer
        self._embedding_model: SentenceTransformer | None = None
        self._tfidf_vectorizer: TfidfVectorizer | None = None
        self._llm_client: LocalLLMClient | None = None

    @property
    def embedding_model(self) -> SentenceTransformer | TfidfVectorizer:
        """Lazy load the sentence transformer model or TF-IDF vectorizer."""
        if self.use_sentence_transformers:
            if self._embedding_model is None:
                self._embedding_model = SentenceTransformer(self.embedding_model_name)
            return self._embedding_model
        else:
            # Fallback to TF-IDF
            if self._tfidf_vectorizer is None:
                self._tfidf_vectorizer = TfidfVectorizer(stop_words='english')
            return self._tfidf_vectorizer

    @property
    def llm_client(self) -> LocalLLMClient:
        """Lazy load the LLM client."""
        if self._llm_client is None:
            self._llm_client = LocalLLMClient(self.settings)
        return self._llm_client

    def analyze_requirements(
        self,
        run_id: int,
        requirements: list[dict[str, Any]],
    ) -> ConsistencyResult:
        """Analyze consistency across all requirements in a run.
        
        Args:
            run_id: The run ID
            requirements: List of requirement dicts with 'id' and 'recommended_text'
            
        Returns:
            ConsistencyResult with all detected relationships
        """
        if len(requirements) < 2:
            return ConsistencyResult(
                run_id=run_id,
                total_requirements=len(requirements),
                relationships=[],
                summary={"duplicates": 0, "similar": 0, "contradictions": 0, "independent": 0},
            )

        # Extract requirement texts and IDs
        req_texts = [req["recommended_text"] for req in requirements]
        req_ids = [req["id"] for req in requirements]

        # Generate embeddings or TF-IDF vectors
        if self.use_sentence_transformers:
            embeddings = self.embedding_model.encode(
                req_texts, show_progress_bar=False, convert_to_numpy=True
            )
        else:
            # Fallback to TF-IDF
            embeddings = self.embedding_model.fit_transform(req_texts).toarray()

        # Compute pairwise similarity matrix
        similarity_matrix = cosine_similarity(embeddings)

        # Analyze each pair
        relationships: list[RequirementRelationship] = []
        n = len(requirements)

        for i in range(n):
            for j in range(i + 1, n):
                similarity = float(similarity_matrix[i][j])
                relationship = self._classify_pair(
                    req_texts[i],
                    req_texts[j],
                    similarity,
                )
                
                if relationship.relationship_type != RelationshipType.INDEPENDENT:
                    relationships.append(relationship)

        # Build summary
        summary = {
            "duplicates": sum(
                1 for r in relationships if r.relationship_type == RelationshipType.DUPLICATE
            ),
            "similar": sum(
                1 for r in relationships if r.relationship_type == RelationshipType.SIMILAR
            ),
            "contradictions": sum(
                1 for r in relationships if r.relationship_type == RelationshipType.CONTRADICTION
            ),
            "independent": (n * (n - 1)) // 2 - len(relationships),
        }

        return ConsistencyResult(
            run_id=run_id,
            total_requirements=n,
            relationships=relationships,
            summary=summary,
        )

    def _classify_pair(
        self,
        text1: str,
        text2: str,
        similarity: float,
    ) -> RequirementRelationship:
        """Classify the relationship between two requirement texts.
        
        Args:
            text1: First requirement text
            text2: Second requirement text
            similarity: Cosine similarity score
            
        Returns:
            RequirementRelationship with classification
        """
        # High similarity - likely duplicate
        if similarity >= self.duplicate_threshold:
            return RequirementRelationship(
                req_id_1=0,  # Will be set by caller
                req_id_2=0,  # Will be set by caller
                relationship_type=RelationshipType.DUPLICATE,
                similarity_score=similarity,
                confidence=similarity,
                reason="Very high semantic similarity indicates duplicate requirement.",
            )

        # Medium similarity - check for contradiction if enabled
        if similarity >= self.similarity_threshold:
            if self.enable_contradiction_check:
                is_contradiction, reason = self._check_contradiction(text1, text2)
                if is_contradiction:
                    return RequirementRelationship(
                        req_id_1=0,
                        req_id_2=0,
                        relationship_type=RelationshipType.CONTRADICTION,
                        similarity_score=similarity,
                        confidence=0.9,  # High confidence from LLM verification
                        reason=reason,
                    )
            
            return RequirementRelationship(
                req_id_1=0,
                req_id_2=0,
                relationship_type=RelationshipType.SIMILAR,
                similarity_score=similarity,
                confidence=similarity,
                reason="High semantic similarity indicates related requirements.",
            )

        # Low similarity - independent
        return RequirementRelationship(
            req_id_1=0,
            req_id_2=0,
            relationship_type=RelationshipType.INDEPENDENT,
            similarity_score=similarity,
            confidence=1.0 - similarity,
            reason=None,
        )

    def _check_contradiction(self, text1: str, text2: str) -> tuple[bool, str]:
        """Use LLM to check if two requirements contradict each other.
        
        Args:
            text1: First requirement text
            text2: Second requirement text
            
        Returns:
            Tuple of (is_contradiction, reason)
        """
        try:
            self.llm_client.check_reachable()
            
            system_prompt = """You are an expert in aerospace requirements engineering. 
Analyze whether two requirements contradict each other.

A contradiction exists when one requirement explicitly prohibits or prevents 
what another requirement mandates or requires.

Respond in JSON format:
{
    "is_contradiction": true/false,
    "reason": "brief explanation of why they do or don't contradict"
}"""

            user_prompt = f"""Requirement 1: {text1}

Requirement 2: {text2}

Do these requirements contradict each other?"""

            response = self.llm_client.generate_structured(
                system_prompt,
                user_prompt,
                temperature=0.1,
            )

            result = response.raw
            is_contradiction = result.get("is_contradiction", False)
            reason = result.get("reason", "No explanation provided")

            return is_contradiction, reason

        except Exception as exc:
            # If LLM check fails, disable contradiction checks for this run
            # and assume no contradiction to avoid false positives
            self.enable_contradiction_check = False
            return False, f"LLM check failed (contradiction detection disabled): {exc}"
