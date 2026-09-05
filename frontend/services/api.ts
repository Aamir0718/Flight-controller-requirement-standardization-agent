import axios from "axios";
import {
  HealthResponse,
  Requirement,
  Run,
  UploadResponse,
  ConsistencyResponse,
  RunProgress,
  EmbeddingMatrixResponse,
} from "@/types";


const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

// Add better error handling with detailed messages
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.code === 'ECONNABORTED') {
      error.message = 'Request timeout. The backend took too long to respond.';
    } else if (error.response) {
      // Server responded with error status
      const status = error.response.status;
      const detail = error.response.data?.detail;
      
      if (status === 404) {
        error.message = detail || 'API endpoint not found. Please check if the backend is running the correct version.';
      } else if (status === 500) {
        error.message = detail || 'Internal server error. Check the backend logs for details.';
      } else if (status === 400) {
        error.message = detail || 'Invalid request. Please check your input.';
      } else if (status === 409) {
        error.message = detail || 'Conflict. The resource is not in the required state.';
      } else {
        error.message = detail || `Server error (${status}). Please try again.`;
      }
    } else if (error.request) {
      // Request made but no response received
      error.message = 'Unable to connect to backend. Please ensure the FastAPI server is running on http://127.0.0.1:8000';
    } else {
      // Something else happened
      error.message = error.message || 'An unexpected error occurred.';
    }
    
    return Promise.reject(error);
  }
);

export const apiService = {
  async getHealth(): Promise<HealthResponse> {
    const { data } = await apiClient.get<HealthResponse>("/health");
    return data;
  },

  async uploadWorkbook(file: File): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<UploadResponse>("/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return data;
  },

  async listRuns(): Promise<Run[]> {
    const { data } = await apiClient.get<Run[]>("/runs");
    return data;
  },

  async getRunStatus(runId: number): Promise<Run> {
    const { data } = await apiClient.get<Run>(`/runs/${runId}`);
    return data;
  },

  async getRunRequirements(runId: number): Promise<Requirement[]> {
    const { data } = await apiClient.get<Requirement[]>(`/runs/${runId}/requirements`);
    return data;
  },

  /** Sends only the given requirement ids to the LLM (one row's Generate
   * button, or Select All + Generate). Runs in the background on the
   * server -- poll getRunRequirements() and watch each id's own `status`
   * flip analyzed -> generating -> generated/failed. */
  async generateRequirements(runId: number, requirementIds: number[]): Promise<{ status: string; requirement_ids: number[] }> {
    const { data } = await apiClient.post(`/runs/${runId}/requirements/generate`, {
      requirement_ids: requirementIds,
    });
    return data;
  },

  /** A human typed a replacement requirement themselves -- no LLM, just a
   * deterministic re-score. Synchronous, returns the updated row. */
  async editRequirement(runId: number, requirementId: number, recommendedText: string): Promise<Requirement> {
    const { data } = await apiClient.put<Requirement>(
      `/runs/${runId}/requirements/${requirementId}`,
      { recommended_text: recommendedText }
    );
    return data;
  },

  /** A human clicked "Check Accurate Score" for one requirement -- runs in
   * the background on the server (a real LLM call for the 14 rules that
   * can't be checked mechanically), same poll-based pattern as
   * generateRequirements(): watch this row's own `accurate_score_status`
   * flip computing -> done/failed via getRunRequirements(). */
  async computeAccurateScore(runId: number, requirementId: number): Promise<{ status: string }> {
    const { data } = await apiClient.post(
      `/runs/${runId}/requirements/${requirementId}/accurate-score`
    );
    return data;
  },

  async getRunConsistency(runId: number): Promise<ConsistencyResponse> {
    const { data } = await apiClient.get<ConsistencyResponse>(`/runs/${runId}/consistency`);
    return data;
  },

  async reanalyzeConsistency(runId: number): Promise<{
    message: string;
    contradiction_check_skipped: boolean;
    summary: Record<string, number>;
    relationships_count: number;
  }> {
    const { data } = await apiClient.post(`/runs/${runId}/reanalyze-consistency`);
    return data;
  },

  async getRunProgress(runId: number, afterSeq: number = -1): Promise<RunProgress> {
    const { data } = await apiClient.get<RunProgress>(`/runs/${runId}/progress`, {
      params: { after_seq: afterSeq },
    });
    return data;
  },

  async getEmbeddingMatrix(runId: number): Promise<EmbeddingMatrixResponse> {
    const { data } = await apiClient.get<EmbeddingMatrixResponse>(`/runs/${runId}/embedding-matrix`);
    return data;
  },

  getDownloadUrl(runId: number): string {
    return `${API_BASE_URL}/runs/${runId}/download`;
  },
};
