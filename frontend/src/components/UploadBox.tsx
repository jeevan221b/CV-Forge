import { FilePlus2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { useSystem } from "../system";
import type { Resume } from "../types";
import { Alert, Button, cx } from "./ui";

export function UploadBox({ onCreated }: { onCreated: (resume: Resume) => void }) {
  const { system } = useSystem();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState("");

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (!/\.(tex|pdf)$/i.test(file.name)) {
      setError("Only .tex and .pdf files can be imported.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onCreated(await api.uploadResume(file));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const manual = async () => {
    setBusy(true);
    setError("");
    try {
      onCreated(await api.createManualResume("Master resume"));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void upload(e.dataTransfer.files[0]);
        }}
        className={cx(
          "flex flex-col items-center rounded-lg border border-dashed px-6 py-8 text-center transition-colors",
          over ? "border-accent-500 bg-accent-50" : "border-slate-300 bg-white",
        )}
      >
        <Upload className="mb-2 h-5 w-5 text-slate-400" aria-hidden />
        <p className="text-sm font-medium text-slate-800">Import your resume</p>
        <p className="mt-1 max-w-md text-xs leading-relaxed text-slate-500">
          Drop a <span className="font-mono">.tex</span> file (most reliable) or a text-based PDF. Up to{" "}
          {system?.limits.max_upload_mb ?? 5} MB. The file is stored unchanged on this machine and is never overwritten.
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Button variant="primary" loading={busy} icon={<Upload className="h-4 w-4" />} onClick={() => input.current?.click()}>
            Choose file
          </Button>
          <Button disabled={busy} icon={<FilePlus2 className="h-4 w-4" />} onClick={manual}>
            Enter manually
          </Button>
        </div>
        <input ref={input} type="file" accept=".tex,.pdf,application/pdf" className="hidden" onChange={(e) => void upload(e.target.files?.[0])} />
      </div>
      {error && (
        <Alert kind="error" className="mt-3" onClose={() => setError("")}>
          {error}
        </Alert>
      )}
    </div>
  );
}
