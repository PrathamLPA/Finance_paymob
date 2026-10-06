"use client";

import { useEffect, useState } from "react";
import { fetchProtectedBlob } from "@/lib/api";

export type ProofState = {
  /** Object URL for <img src> or <a href>. Null while loading or on error. */
  url: string | null;
  isPdf: boolean;
  loading: boolean;
  error: string;
};

/**
 * Load a private proof file (image or PDF) through the API with the staff
 * token. Re-fetches only when the path changes, so re-renders of the parent
 * (e.g. after approve) do not flash the image.
 */
export function useProof(
  proofPath: string | null | undefined,
  contentType?: string | null
): ProofState {
  const [state, setState] = useState<ProofState>({
    url: null,
    isPdf: contentType === "application/pdf",
    loading: Boolean(proofPath),
    error: "",
  });

  useEffect(() => {
    if (!proofPath) {
      setState({ url: null, isPdf: false, loading: false, error: "" });
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState({
      url: null,
      isPdf: contentType === "application/pdf",
      loading: true,
      error: "",
    });
    fetchProtectedBlob(proofPath, controller.signal)
      .then(({ url, type }) => {
        if (controller.signal.aborted) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setState({
          url,
          isPdf: type === "application/pdf" || contentType === "application/pdf",
          loading: false,
          error: "",
        });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          url: null,
          isPdf: contentType === "application/pdf",
          loading: false,
          error: err instanceof Error ? err.message : "Could not load file",
        });
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [proofPath, contentType]);

  return state;
}
