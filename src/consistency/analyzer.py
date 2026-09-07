"""Consistency analyzer for detecting duplicate, similar, and contradictory requirements.

Uses sentence embeddings for semantic similarity and the configured LLM endpoint for contradiction detection.
Falls back to TF-IDF if sentence-transformers is blocked by system security policies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import get_settings
from llm.local_llm_client import LocalLLMClient

_CONTRADICTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_contradiction": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["is_contradiction", "reason"],
}
_CONTRADICTION_REQUIRED_KEYS = {"is_contradiction", "reason"}

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
    """Result of consistency analysis for a run.

    ``contradiction_check_skipped`` is True when contradiction detection
    was configured on (consistency.enable_contradiction_check) but the LLM
    wasn't reachable when this analysis ran -- duplicate/similarity
    detection (pure embeddings, no LLM) still completed normally either
    way. Lets callers surface one clear "contradiction detection was
    skipped, LLM not reachable" message instead of a human having to
    notice it's buried in every affected pair's own reason text.
    """
    run_id: int
    total_requirements: int
    relationships: list[RequirementRelationship]
    summary: dict[str, int]
    contradiction_check_skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_requirements": self.total_requirements,
            "relationships": [r.to_dict() for r in self.relationships],
            "summary": self.summary,
            "contradiction_check_skipped": self.contradiction_check_skipped,
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
        # Checked once per analyzer instance (i.e. once per analyze_requirements()
        # call), not once per pair -- see _is_llm_reachable().
        self._llm_reachable: bool | None = None

    @property
    def embedding_model(self) -> SentenceTransformer | TfidfVectorizer:
        """Lazy load the sentence transformer model or TF-IDF vectorizer."""
        if self.use_sentence_transformers:
            if self._embedding_model is None:
                self._embedding_model = SentenceTransformer(self.embedding_model_name)
            return self._embedding_model
        else:
            # Fallback to TF-IDF. Negation words are deliberately kept out
            # of the stop-word list -- sklearn's default English stop words
            # include "not"/"no"/"never", which would make "X shall enable Y"
            # and "X shall not enable Y" look nearly identical (both routing
            # to DUPLICATE) instead of flowing into the LLM contradiction
            # check where they belong.
            if self._tfidf_vectorizer is None:
                negation_safe_stop_words = frozenset(
                    TfidfVectorizer(stop_words="english").get_stop_words()
                ) - {"not", "no", "never", "cannot", "none", "nor"}
                self._tfidf_vectorizer = TfidfVectorizer(
                    stop_words=list(negation_safe_stop_words)
                )
            return self._tfidf_vectorizer
                            

    @property
    def llm_client(self) -> LocalLLMClient:
        """Lazy load the LLM client."""
        if self._llm_client is None:
            self._llm_client = LocalLLMClient(self.settings)
        return self._llm_client

    def _is_llm_reachable(self) -> bool:
        """Checks LLM endpoint reachability ONCE per analyze_requirements() call
        and caches the result -- calling check_reachable() once per
        candidate pair (as this used to do, inside _check_contradiction())
        means a run with dozens of medium-similarity pairs would retry a
        doomed connection dozens of times before giving up, for no benefit
        (the answer doesn't change pair to pair). One check up front is
        both faster and lets the caller report one clear reason instead of
        it being silently buried in every affected pair's own text.
        """
        if self._llm_reachable is None:
            try:
                self.llm_client.check_reachable()
                self._llm_reachable = True
            except Exception:
                self._llm_reachable = False
        return self._llm_reachable

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
                    relationships.append(
                        replace(relationship, req_id_1=req_ids[i], req_id_2=req_ids[j])
                    )

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
            # True only if contradiction checking was actually attempted
            # (enable_contradiction_check on, at least one pair reached
            # similarity_threshold) and the LLM turned out unreachable --
            # self._llm_reachable stays None (not False) if it was never
            # checked at all, which must NOT be reported as "skipped".
            contradiction_check_skipped=self._llm_reachable is False,
        )

    def compute_pairwise_similarities(self, requirements: list[dict[str, Any]]) -> dict[str, Any]:
        """Computes the raw cosine similarity for every pair of requirements
        (all n*(n-1)/2 combinations, not just the ones that clear
        duplicate_threshold/similarity_threshold) -- for the Embedding
        Distance tab, which needs every pair's angle, not a filtered
        relationship classification.

        Deliberately does not call _classify_pair()/the LLM contradiction
        check: this is a pure embedding (or TF-IDF fallback) + cosine
        similarity computation, so it stays fast and safe to recompute on
        every tab open even for a 100-requirement run (~5000 pairs).
        """
        if len(requirements) < 2:
            return {
                "pairs": [],
                "method": "sentence-transformers" if self.use_sentence_transformers else "tfidf",
                "total_requirements": len(requirements),
            }

        req_texts = [req["recommended_text"] for req in requirements]
        req_ids = [req["id"] for req in requirements]

        if self.use_sentence_transformers:
            embeddings = self.embedding_model.encode(
                req_texts, show_progress_bar=False, convert_to_numpy=True
            )
        else:
            embeddings = self.embedding_model.fit_transform(req_texts).toarray()

        similarity_matrix = cosine_similarity(embeddings)

        pairs: list[dict[str, Any]] = []
        n = len(requirements)
        for i in range(n):
            for j in range(i + 1, n):
                # Cosine similarity IS the cosine of the angle between the
                # two embedding vectors -- clamp before acos() since
                # floating-point rounding can push it a hair outside
                # [-1, 1] and make acos() raise.
                similarity = float(similarity_matrix[i][j])
                clamped = max(-1.0, min(1.0, similarity))
                angle_degrees = float(np.degrees(np.arccos(clamped)))
                pairs.append(
                    {
                        "req_id_1": req_ids[i],
                        "req_id_2": req_ids[j],
                        "similarity": similarity,
                        "distance": 1.0 - similarity,
                        "angle_degrees": angle_degrees,
                    }
                )

        return {
            "pairs": pairs,
            "method": "sentence-transformers" if self.use_sentence_transformers else "tfidf",
            "total_requirements": n,
        }

    def _classify_pair(
        self,
        text1: str,
        text2: str,
        similarity: float,
    ) -> RequirementRelationship:
        """Classify the relationship between two requirement texts.

        Order matters here, and it's deliberately NOT "duplicate first,
        then check contradiction for what's left": a contradiction pair
        (same subject, one word flipped -- e.g. "shall enable X" vs
        "shall not enable X") is often textually so close it clears
        duplicate_threshold too. If duplicate were checked first, every
        such pair would be mislabeled "Duplicate" and the contradiction
        check would never even run on it -- silently hiding the more
        serious defect (two requirements that actively conflict) behind
        the more benign one (near-identical wording). So: any pair that
        clears similarity_threshold gets the contradiction check FIRST,
        regardless of how high its similarity is; only once that comes
        back negative (or can't be checked) does duplicate-vs-similar
        get decided.

        Args:
            text1: First requirement text
            text2: Second requirement text
            similarity: Cosine similarity score

        Returns:
            RequirementRelationship with classification
        """
        if similarity >= self.similarity_threshold:
            if self.enable_contradiction_check and self._is_llm_reachable():
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

            if similarity >= self.duplicate_threshold:
                return RequirementRelationship(
                    req_id_1=0,  # Will be set by caller
                    req_id_2=0,  # Will be set by caller
                    relationship_type=RelationshipType.DUPLICATE,
                    similarity_score=similarity,
                    confidence=similarity,
                    reason="Very high semantic similarity indicates duplicate requirement.",
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
        Only ever called after _is_llm_reachable() has already confirmed
        the endpoint is up (see _classify_pair) -- no redundant check_reachable()
        call here; the try/except below is a safety net for the LLM
        dropping mid-batch, not the primary "is it even up" gate.

        Args:
            text1: First requirement text
            text2: Second requirement text

        Returns:
            Tuple of (is_contradiction, reason)
        """
        try:
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

            result = self.llm_client.generate_json(
                system_prompt,
                user_prompt,
                schema=_CONTRADICTION_SCHEMA,
                required_keys=_CONTRADICTION_REQUIRED_KEYS,
                temperature=0.1,
            )

            is_contradiction = result.get("is_contradiction", False)
            reason = result.get("reason", "No explanation provided")

            return is_contradiction, reason

        except Exception as exc:
            # A single bad/failed response only affects THIS pair -- it must
            # not disable contradiction checking for the rest of the run,
            # otherwise one hiccup silently blinds every later pair (e.g. a
            # real contradiction later in the batch would go unreported).
            return False, f"LLM check failed for this pair (treated as no contradiction): {exc}"
