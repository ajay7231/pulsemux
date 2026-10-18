import { useQuery } from "@tanstack/react-query";
import { useSession } from "../../app/SessionProvider";
import { workspaceKey } from "../../app/useWorkspaceQueries";
import { metadataService } from "../../services/platform";

export function ModelSelect({
  connectionId,
  revision,
  value,
  onChange,
}: {
  connectionId: string | null;
  revision?: number;
  value: string;
  onChange: (value: string) => void;
}) {
  const { session } = useSession();
  const catalog = useQuery({
    queryKey: [
      ...workspaceKey(session!.workspace.id),
      "models",
      connectionId,
      revision,
    ],
    enabled: !!connectionId,
    staleTime: 300000,
    queryFn: ({ signal }) => metadataService.models(connectionId!, signal),
  });
  const result = catalog.data;
  const loading = !!connectionId && catalog.isFetching;
  const error = catalog.error?.message || "";
  const models = result?.models || [];
  const unavailable = !!value && !models.some((model) => model.id === value);
  return (
    <div className="model-picker">
      <label className="field">
        <span>Language model</span>
        <select
          aria-label="Language model"
          aria-describedby="model-help"
          value={value || ""}
          disabled={!connectionId || loading || !!error || !models.length}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">
            {!connectionId
              ? "Connect a provider first"
              : loading
                ? "Loading available models…"
                : error
                  ? "Models unavailable — retry below"
                  : !models.length
                    ? "No compatible models found"
                    : "Choose a language model"}
          </option>
          {unavailable && connectionId && (
            <option value={value} disabled>
              {value} · {loading ? "checking availability" : "unavailable"}
            </option>
          )}
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name}
            </option>
          ))}
        </select>
        <small id="model-help">
          {!connectionId
            ? "Add or select a Groq or OpenAI connection to see its models."
            : "Models available to this account that are supported by the voice agent."}
        </small>
      </label>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      {!loading && result && unavailable && (
        <p className="field-error">
          The saved model is no longer available here. Choose another model
          before testing.
        </p>
      )}
      {!loading && result && !models.length && (
        <p className="field-error">
          This account returned no compatible text models. Check model access or
          choose another connection.
        </p>
      )}
      {connectionId && (
        <button
          type="button"
          className="text-button"
          disabled={loading}
          onClick={() => void catalog.refetch()}
        >
          {error ? "Retry loading models" : "Refresh models"}
        </button>
      )}
    </div>
  );
}
