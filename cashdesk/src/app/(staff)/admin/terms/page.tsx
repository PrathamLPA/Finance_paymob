"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/toast";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { SkeletonBlock } from "@/components/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Version = {
  id: number | null;
  version: string;
  note: string | null;
  published_by: string | null;
  published_at: string | null;
  is_active: boolean;
  content?: string;
  html?: string;
};

type TermsState = {
  active: Version & { content: string; html: string };
  built_in_content: string;
  history: Version[];
};

type PreviewMode = "popup" | "page";

// The customer pages and their styles are served from the same site as this app.
// While developing locally they are on another address; set it in that case.
const CUSTOMER_BASE = process.env.NEXT_PUBLIC_CUSTOMER_BASE_URL ?? "";

function when(value: string | null) {
  return value ? new Date(value).toLocaleString() : "built-in";
}

/** A page that looks like what the customer sees, using the customer stylesheet. */
function previewDocument(html: string, mode: PreviewMode, version: string): string {
  const head = `<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="${CUSTOMER_BASE}/static/styles.css?v=27">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Source+Serif+4:wght@600;700&display=swap" rel="stylesheet">
<base target="_blank">`;
  if (mode === "popup") {
    return `<!doctype html><html><head>${head}
<style>body{margin:0;background:#e7e5e4;padding:18px;font-family:'DM Sans',system-ui,sans-serif}
.preview-dialog{max-width:560px;margin:0 auto;background:#fff;border-radius:18px;box-shadow:0 20px 50px -24px rgba(15,23,42,.45);overflow:hidden}
.preview-head{padding:16px 20px;border-bottom:1px solid #e7e5e4}
.preview-head p{margin:0;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#0f766e;font-weight:600}
.preview-head h2{margin:2px 0 0;font-size:18px}
.preview-body{padding:6px 20px 20px}
.preview-end{text-align:center;font-size:12px;color:#78716c;padding-top:12px}</style></head>
<body><div class="preview-dialog"><div class="preview-head"><p>Learners Point</p><h2>Terms &amp; Refund Policy</h2></div>
<div class="preview-body"><article class="policy-article terms-modal-article">${html}</article>
<p class="preview-end">End of policy</p></div></div></body></html>`;
  }
  return `<!doctype html><html><head>${head}</head>
<body class="policy-page"><div class="policy-bg" aria-hidden="true"></div>
<main class="policy-main"><header class="policy-hero"><p class="policy-eyebrow">Legal</p>
<h1 class="policy-title">Terms and Conditions &amp; Refund Policy</h1>
<p class="policy-lead">How we collect and use your information, protect payments, and handle refunds or complaints.</p></header>
<article class="policy-article">${html}</article>
<p class="policy-version">Version ${version}</p></main></body></html>`;
}

function TermsEditor() {
  const toast = useToast();
  const [state, setState] = useState<TermsState | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [html, setHtml] = useState("");
  const [mode, setMode] = useState<PreviewMode>("popup");
  const [error, setError] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [busyRestore, setBusyRestore] = useState<number | null>(null);
  const loadedText = useRef("");

  const load = useCallback(async () => {
    const res = await api<TermsState>("/api/staff/admin/terms");
    setState(res);
    setDraft(res.active.content);
    setHtml(res.active.html);
    loadedText.current = res.active.content;
  }, []);

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Could not load the terms"));
  }, [load]);

  // Preview follows what is typed, a moment after typing stops.
  useEffect(() => {
    if (!state) return;
    if (draft === loadedText.current) {
      setHtml(state.active.html);
      return;
    }
    const timer = setTimeout(() => {
      api<{ html: string }>("/api/staff/admin/terms/preview", {
        method: "POST",
        body: JSON.stringify({ content: draft }),
      })
        .then((res) => setHtml(res.html))
        .catch(() => undefined);
    }, 350);
    return () => clearTimeout(timer);
  }, [draft, state]);

  const changed = state !== null && draft.trim() !== loadedText.current.trim();

  // Warn before leaving the page with edits that were not published.
  useEffect(() => {
    if (!changed) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changed]);

  async function publish() {
    if (
      !window.confirm(
        "Publish this text? Customers will see it from their next page load, and every payment accepted after this records the new version."
      )
    ) {
      return;
    }
    setPublishing(true);
    setError("");
    try {
      const res = await api<Version>("/api/staff/admin/terms", {
        method: "POST",
        body: JSON.stringify({ content: draft, note: note || null }),
      });
      setNote("");
      await load();
      toast.show({
        tone: "success",
        title: `Published version ${res.version}`,
        detail: "Customers see it from their next page load (within about 30 seconds).",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not publish");
    } finally {
      setPublishing(false);
    }
  }

  async function restore(item: Version) {
    if (item.id === null) return;
    if (!window.confirm(`Publish version ${item.version} again as a new version?`)) return;
    setBusyRestore(item.id);
    setError("");
    try {
      const res = await api<Version>(`/api/staff/admin/terms/${item.id}/restore`, { method: "POST" });
      await load();
      toast.show({ tone: "success", title: `Restored. Now published as version ${res.version}` });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not restore");
    } finally {
      setBusyRestore(null);
    }
  }

  async function viewVersion(item: Version) {
    if (item.id === null) return;
    try {
      const detail = await api<{ content: string }>(`/api/staff/admin/terms/${item.id}`);
      setDraft(detail.content);
      toast.show({ tone: "info", title: `Loaded version ${item.version} into the editor (not published)` });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load that version");
    }
  }

  const doc = useMemo(
    () => previewDocument(html, mode, state?.active.version ?? ""),
    [html, mode, state]
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Terms & policy"
        description="The Terms and Conditions customers read and accept on the payment page. Edit the text, check the preview, then publish."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      {!state ? (
        <Card>
          <CardContent>
            <SkeletonBlock lines={6} />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle>Edit the text</CardTitle>
                  <Badge variant="success">Live: version {state.active.version}</Badge>
                  {changed ? <Badge variant="warning">Unpublished changes</Badge> : null}
                </div>
                <CardDescription>
                  Start a section with <code className="rounded bg-stone-100 px-1">## Heading</code>. Leave a blank
                  line between paragraphs. Use <code className="rounded bg-stone-100 px-1">- </code> for bullets,{" "}
                  <code className="rounded bg-stone-100 px-1">**bold**</code> for bold and{" "}
                  <code className="rounded bg-stone-100 px-1">[text](https://link)</code> or{" "}
                  <code className="rounded bg-stone-100 px-1">[text](mailto:a@b.com)</code> for links.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  spellCheck
                  className="h-[28rem] w-full resize-y rounded-md border border-stone-300 bg-white p-3 font-mono text-[13px] leading-relaxed text-stone-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-700"
                  aria-label="Terms and Conditions text"
                />
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-stone-500">
                  <span>{draft.length.toLocaleString()} characters</span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!changed}
                      onClick={() => setDraft(loadedText.current)}
                    >
                      Discard changes
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDraft(state.built_in_content)}
                    >
                      Use the original text
                    </Button>
                  </div>
                </div>
                <input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  maxLength={255}
                  placeholder="What changed? (optional, saved in the history)"
                  className="h-10 w-full rounded-md border border-stone-300 px-3 text-sm"
                />
                <Button loading={publishing} disabled={!changed} onClick={publish} className="w-full sm:w-auto">
                  Publish to customers
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>What the customer sees</CardTitle>
                  <div className="flex gap-1 rounded-lg bg-stone-100 p-1 text-xs">
                    {(
                      [
                        ["popup", "Pop-up on payment page"],
                        ["page", "Full page"],
                      ] as [PreviewMode, string][]
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setMode(key)}
                        className={`rounded-md px-3 py-1.5 font-medium transition ${
                          mode === key ? "bg-white text-stone-900 shadow-sm" : "text-stone-600 hover:text-stone-900"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <CardDescription>
                  {changed
                    ? "A preview of your edit. Customers do not see it until you publish."
                    : "This is what customers see right now."}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <iframe
                  title="Preview of the Terms and Conditions"
                  srcDoc={doc}
                  sandbox="allow-same-origin allow-popups"
                  className="h-[32rem] w-full rounded-lg border border-stone-200 bg-white"
                />
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Version history</CardTitle>
              <CardDescription>
                Every published version is kept. Each customer&apos;s acceptance records the version they saw.
              </CardDescription>
            </CardHeader>
            <CardContent className="divide-y divide-stone-100 px-0 pb-0">
              {state.history.length === 0 ? (
                <p className="px-6 py-6 text-sm text-stone-500">
                  Nothing published yet. Customers see the original text that came with the app (version{" "}
                  {state.active.version}).
                </p>
              ) : (
                state.history.map((item) => (
                  <div key={item.id ?? item.version} className="flex flex-wrap items-center gap-3 px-6 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                        Version {item.version}
                        {item.is_active ? <Badge variant="success">Live</Badge> : null}
                      </div>
                      <div className="text-xs text-stone-500">
                        {when(item.published_at)}
                        {item.published_by ? ` · ${item.published_by}` : ""}
                        {item.note ? ` · ${item.note}` : ""}
                      </div>
                    </div>
                    <Button size="sm" variant="outline" onClick={() => void viewVersion(item)}>
                      Load into editor
                    </Button>
                    {!item.is_active ? (
                      <Button
                        size="sm"
                        variant="outline"
                        loading={busyRestore === item.id}
                        onClick={() => void restore(item)}
                      >
                        Publish again
                      </Button>
                    ) : null}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

export default function AdminTermsPage() {
  return <RequireAuth role="admin">{() => <TermsEditor />}</RequireAuth>;
}
