import axios from "axios";
import { HealthResponse, Requirement, Run, UploadResponse, ConsistencyResponse } from "@/types";


const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

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

  async getRunConsistency(runId: number): Promise<ConsistencyResponse> {
    const { data } = await apiClient.get<ConsistencyResponse>(`/runs/${runId}/consistency`);
    return data;
  },

  async reanalyzeConsistency(runId: number): Promise<{ message: string; summary: Record<string, number>; relationships_count: number }> {
    const { data } = await apiClient.post(`/runs/${runId}/reanalyze-consistency`);
    return data;
  },

  getDownloadUrl(runId: number): string {
    return `${API_BASE_URL}/runs/${runId}/download`;
  },
};
