"""Client for pactown registry."""

from pathlib import Path
from typing import Optional

import httpx


class RegistryClient:
    """Client for interacting with pactown registry."""

    def __init__(self, base_url: str = "http://localhost:8800", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def close(self):
        self._client.close()

    def health(self) -> bool:
        """Check if registry is healthy."""
        try:
            response = self._client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    def list_artifacts(
        self,
        namespace: Optional[str] = None,
        search: Optional[str] = None
    ) -> list[dict]:
        """List artifacts in the registry."""
        params = {}
        if namespace:
            params["namespace"] = namespace
        if search:
            params["search"] = search

        response = self._client.get(f"{self.base_url}/v1/artifacts", params=params)
        response.raise_for_status()
        return response.json()

    def get_artifact(self, name: str, namespace: str = "default") -> Optional[dict]:
        """Get artifact information."""
        try:
            response = self._client.get(
                f"{self.base_url}/v1/artifacts/{namespace}/{name}"
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

    def get_version(
        self,
        name: str,
        version: str = "latest",
        namespace: str = "default"
    ) -> Optional[dict]:
        """Get specific version information."""
        try:
            response = self._client.get(
                f"{self.base_url}/v1/artifacts/{namespace}/{name}/{version}"
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

    def get_readme(
        self,
        name: str,
        version: str = "latest",
        namespace: str = "default"
    ) -> Optional[str]:
        """Get README content for a specific version."""
        try:
            response = self._client.get(
                f"{self.base_url}/v1/artifacts/{namespace}/{name}/{version}/readme"
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json().get("content")
        except httpx.HTTPStatusError:
            return None

    def publish(
        self,
        name: str,
        version: str,
        readme_path: Optional[Path] = None,
        readme_content: Optional[str] = None,
        namespace: str = "default",
        description: str = "",
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Publish an artifact to the registry."""
        if readme_path:
            readme_content = Path(readme_path).read_text()

        if not readme_content:
            raise ValueError("Either readme_path or readme_content must be provided")

        payload = {
            "name": name,
            "version": version,
            "readme_content": readme_content,
            "namespace": namespace,
            "description": description,
            "tags": tags or [],
            "metadata": metadata or {},
        }

        try:
            response = self._client.post(f"{self.base_url}/v1/publish", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": str(e)}

    def pull(
        self,
        name: str,
        version: str = "latest",
        namespace: str = "default",
        output_path: Optional[Path] = None,
    ) -> Optional[str]:
        """Pull an artifact from the registry."""
        readme = self.get_readme(name, version, namespace)

        if readme and output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(readme)

        return readme

    def delete(self, name: str, namespace: str = "default") -> bool:
        """Delete an artifact from the registry."""
        try:
            response = self._client.delete(
                f"{self.base_url}/v1/artifacts/{namespace}/{name}"
            )
            return response.status_code == 200
        except httpx.HTTPStatusError:
            return False

    def list_namespaces(self) -> list[str]:
        """List all namespaces."""
        try:
            response = self._client.get(f"{self.base_url}/v1/namespaces")
            response.raise_for_status()
            return response.json().get("namespaces", [])
        except httpx.HTTPStatusError:
            return []


class AsyncRegistryClient:
    """Async client for pactown registry."""

    def __init__(self, base_url: str = "http://localhost:8800", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def close(self):
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    async def list_artifacts(
        self,
        namespace: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict]:
        params = {}
        if namespace:
            params["namespace"] = namespace
        if search:
            params["search"] = search

        response = await self._client.get(f"{self.base_url}/v1/artifacts", params=params)
        response.raise_for_status()
        return response.json()

    async def get_readme(
        self,
        name: str,
        version: str = "latest",
        namespace: str = "default"
    ) -> Optional[str]:
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/artifacts/{namespace}/{name}/{version}/readme"
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json().get("content")
        except httpx.HTTPStatusError:
            return None

    async def publish(
        self,
        name: str,
        version: str,
        readme_content: str,
        namespace: str = "default",
        description: str = "",
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        payload = {
            "name": name,
            "version": version,
            "readme_content": readme_content,
            "namespace": namespace,
            "description": description,
            "tags": tags or [],
            "metadata": metadata or {},
        }

        try:
            response = await self._client.post(f"{self.base_url}/v1/publish", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": str(e)}
