"""Tiny LLM client. Standard library only, so it installs nowhere and runs anywhere.

Provider selection (first match wins):
  1. PITCHPROOF_PROVIDER = azure | github | mock
  2. AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY  -> azure (Azure OpenAI / Microsoft Foundry)
  3. otherwise                                     -> mock (offline template narrator, no model)
GitHub Models is opt-in only: set PITCHPROOF_PROVIDER=github and GITHUB_MODELS_TOKEN.

Environment variables:
  AZURE_OPENAI_ENDPOINT      e.g. https://my-resource.openai.azure.com
  AZURE_OPENAI_API_KEY
  AZURE_OPENAI_DEPLOYMENT    deployment name (default: gpt-4o-mini)
  AZURE_OPENAI_API_VERSION   (default: 2024-06-01)
  GITHUB_MODELS_TOKEN        a GitHub token with access to GitHub Models (github provider only)
  GITHUB_MODEL               (default: openai/gpt-4o-mini)
"""
import json
import os
import urllib.error
import urllib.request


class LLMError(Exception):
    """Raised when a model call fails. The pipeline treats this as a failed attempt."""


def provider():
    explicit = os.environ.get("PITCHPROOF_PROVIDER")
    if explicit:
        return explicit.lower()
    # Only credentials created for this project are auto-detected. A general-purpose
    # GITHUB_TOKEN (used by git / gh) is never picked up silently: GitHub Models must
    # be chosen explicitly with PITCHPROOF_PROVIDER=github.
    if os.environ.get("AZURE_OPENAI_ENDPOINT") and os.environ.get("AZURE_OPENAI_API_KEY"):
        return "azure"
    return "mock"


def _post(url, headers, body, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"network error: {e}") from e


def complete(system, user, temperature=0.2):
    """Return the model's text reply for a system + user prompt."""
    p = provider()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if p == "azure":
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}"
        data = _post(url, {"api-key": os.environ["AZURE_OPENAI_API_KEY"]},
                     {"messages": messages, "temperature": temperature})
    elif p == "github":
        url = "https://models.github.ai/inference/chat/completions"
        model = os.environ.get("GITHUB_MODEL", "openai/gpt-4o-mini")
        token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise LLMError("set GITHUB_MODELS_TOKEN to use the github provider")
        data = _post(url, {"Authorization": f"Bearer {token}"},
                     {"model": model, "messages": messages, "temperature": temperature})
    else:
        raise LLMError("mock provider has no model; the Narrator uses templates instead")
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected response shape: {str(data)[:200]}") from e
