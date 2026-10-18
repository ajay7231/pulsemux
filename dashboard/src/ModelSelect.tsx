import { useEffect, useState } from "react";

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
  const [result, setResult] = useState<{
    connection: string;
    models: { id: string; name: string }[];
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setResult(null);
    setError("");
    if (!connectionId) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    fetch(`/api/connections/${encodeURIComponent(connectionId)}/models`, {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.detail || "Could not load models.");
        return data;
      })
      .then((data) => {
        if (!controller.signal.aborted)
          setResult({ connection: connectionId, models: data.models });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [connectionId, revision, retry]);
  const models = result?.connection === connectionId ? result.models : [];
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
          onClick={() => setRetry((value) => value + 1)}
        >
          {error ? "Retry loading models" : "Refresh models"}
        </button>
      )}
    </div>
  );
}
