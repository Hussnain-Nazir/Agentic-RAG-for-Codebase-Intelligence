import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileArchive, Github, UploadCloud } from "lucide-react";

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

  return (
    <Shell title="Add repository">
      <div className="grid gap-5 lg:grid-cols-2">
        <section className="panel p-7">
          <div className="flex items-center gap-2.5">
            <Github size={18} strokeWidth={1.75} className="text-ink-muted" />
            <h2 className="text-lg font-medium text-ink-primary">Connect GitHub</h2>
          </div>
          <p className="mt-2 text-sm text-ink-secondary">Choose repositories through the Prism GitHub App.</p>
          <button type="button" className="button-primary mt-6" onClick={() => void connectGitHub()} disabled={install.isPending}>
            {install.isPending ? "Connecting..." : "Connect GitHub"}
          </button>
          <div>
            <Link to="/repositories/new/github" className="mt-4 inline-block text-sm font-medium text-accent-hover underline underline-offset-2">
              Choose from connected repositories
            </Link>
          </div>
          {install.isError && <div className="mt-4"><ErrorNotice message={install.error.message} /></div>}
        </section>

        <section className="panel p-7">
          <div className="flex items-center gap-2.5">
            <FileArchive size={18} strokeWidth={1.75} className="text-ink-muted" />
            <h2 className="text-lg font-medium text-ink-primary">Upload ZIP</h2>
          </div>
          <p className="mt-2 text-sm text-ink-secondary">Upload a repository archive up to 200 MB.</p>
          <div
            className={`mt-6 flex flex-col items-center rounded-lg border-2 border-dashed p-8 text-center transition-colors duration-150 ${dragging ? "border-accent bg-accent-subtle" : "border-border-strong"}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <UploadCloud size={22} strokeWidth={1.5} className="mb-3 text-ink-muted" />
            <p className="text-sm text-ink-secondary">Drag a ZIP archive here</p>
            <button type="button" className="mt-3 text-sm font-medium text-accent-hover underline underline-offset-2" onClick={() => input.current?.click()}>
              Choose file
            </button>
            <input ref={input} type="file" accept=".zip,application/zip" className="sr-only" aria-label="ZIP archive" onChange={onInput} />
          </div>
          {file && <p className="mt-4 text-sm text-ink-secondary">Selected: {file.name}</p>}
          {error && <div className="mt-4"><ErrorNotice message={error} /></div>}
          {upload.isError && <div className="mt-4"><ErrorNotice message={upload.error.message} /></div>}
          {upload.isPending && <div className="mt-4">
            <label htmlFor="upload-progress" className="text-sm text-ink-secondary">Uploading: {progress}%</label>
            <progress id="upload-progress" max={100} value={progress} className="mt-2 w-full accent-accent" />
          </div>}
          <button type="button" className="button-primary mt-6" disabled={!file || upload.isPending} onClick={() => void startUpload()}>
            {upload.isPending ? "Uploading..." : "Upload repository"}
          </button>
        </section>
      </div>
    </Shell>
  );
}
