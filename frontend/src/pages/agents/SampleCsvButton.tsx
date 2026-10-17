import { useState } from "react";
import { Download } from "lucide-react";
import { agentApi } from "../../api/endpoints";
import type { Agent } from "../../api/types";
import { Button } from "../../components/Button";
import { useToast } from "../../components/Toast";
import { saveFile } from "../../lib/download";

/** Fetches the agent's sample cohort CSV with the auth header and saves it. */
export function useSampleCsvDownload() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function download(agent: Pick<Agent, "id" | "name">) {
    setBusy(true);
    try {
      const { blob, filename } = await agentApi.sampleCsv(agent.id);
      saveFile(blob, filename ?? `sample-${agent.name}.csv`);
    } catch (err) {
      toast.apiError("Couldn't download the sample CSV", err);
    } finally {
      setBusy(false);
    }
  }
  return { download, busy };
}

export function SampleCsvButton({ agent, size = "sm" }: { agent: Pick<Agent, "id" | "name">; size?: "sm" | "md" }) {
  const { download, busy } = useSampleCsvDownload();
  return (
    <Button size={size} icon={<Download size={14} />} loading={busy} onClick={() => download(agent)}>
      Sample CSV
    </Button>
  );
}
