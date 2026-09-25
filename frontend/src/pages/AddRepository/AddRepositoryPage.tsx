import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useInstallUrl, useUploadRepository } from "../../api/hooks";
import { ErrorNotice, Shell } from "../../components/common/Shell";

export const MAX_ZIP_BYTES = 200 * 1024 * 1024;

export function AddRepositoryPage() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const install = useInstallUrl();
  const upload = useUploadRepository();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);

  function selectFile(candidate: File | null) {
    setError(null);
    setProgress(0);
    setFile(null);
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".zip")) {
      setError("Choose a ZIP archive.");
      return;
    }
    if (candidate.size > MAX_ZIP_BYTES) {
      setError("ZIP archives must be 200 MB or smaller.");
      return;
    }
    setFile(candidate);
  }

  function onInput(event: ChangeEvent<HTMLInputElement>) { selectFile(event.target.files?.[0] ?? null); }
  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files[0] ?? null);
  }

  async function connectGitHub() {
    try {
      const result = await install.mutateAsync();
      window.location.assign(result.url);
    } catch { /* The mutation error is displayed below. */ }
  }

  async function startUpload() {
    if (!file) return;
    setError(null);
    try {
      const result = await upload.mutateAsync({ file, onProgress: setProgress });
      navigate(`/repositories/${result.repository_id}/indexing`);
    } catch { /* The mutation error is displayed below. */ }
  }

  return <Shell title="Add repository">
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-7">
        <h2 className="text-xl font-semibold">Connect GitHub</h2>
        <p className="mt-2 text-sm text-slate-400">Choose repositories through the Prism GitHub App.</p>
        <button type="button" className="button-primary mt-6" onClick={() => void connectGitHub()} disabled={install.isPending}>
          {install.isPending ? "Connecting..." : "Connect GitHub"}
        </button>
        <Link to="/repositories/new/github" className="ml-4 text-sm text-cyan-300 underline">Choose from connected repositories</Link>
        {install.isError && <div className="mt-4"><ErrorNotice message={install.error.message} /></div>}
      </section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-7">
        <h2 className="text-xl font-semibold">Upload ZIP</h2>
        <p className="mt-2 text-sm text-slate-400">Upload a repository archive up to 200 MB.</p>
        <div
          className={`mt-6 rounded-lg border-2 border-dashed p-8 text-center ${dragging ? "border-cyan-400 bg-slate-800" : "border-slate-600"}`}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <p>Drag a ZIP archive here</p>
          <button type="button" className="mt-3 text-sm text-cyan-300 underline" onClick={() => input.current?.click()}>Choose file</button>
          <input ref={input} type="file" accept=".zip,application/zip" className="sr-only" aria-label="ZIP archive" onChange={onInput} />
        </div>
        {file && <p className="mt-4 text-sm">Selected: {file.name}</p>}
        {error && <div className="mt-4"><ErrorNotice message={error} /></div>}
        {upload.isError && <div className="mt-4"><ErrorNotice message={upload.error.message} /></div>}
        {upload.isPending && <div className="mt-4">
          <label htmlFor="upload-progress" className="text-sm">Uploading: {progress}%</label>
          <progress id="upload-progress" max={100} value={progress} className="mt-2 w-full" />
        </div>}
        <button type="button" className="button-primary mt-6" disabled={!file || upload.isPending} onClick={() => void startUpload()}>
          {upload.isPending ? "Uploading..." : "Upload repository"}
        </button>
      </section>
    </div>
  </Shell>;
}
