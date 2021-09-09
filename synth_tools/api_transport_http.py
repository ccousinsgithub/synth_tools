import logging
from typing import Any, Dict, Optional, Tuple

from kentik_api import KentikAPI

from .api_transport import KentikAPIRequestError, KentikAPITransport

log = logging.getLogger("api_transport_http")


class SynthHTTPTransport(KentikAPITransport):
    HTTP_SUCCESS_CODES = (200, 201)
    OPS: Dict[str, Dict[str, Any]] = dict(
        AgentsList=dict(ep="agents", method="get", resp="agents"),
        AgentGet=dict(ep="agents", method="get", params="{id}", resp="agent"),
        AgentPatch=dict(ep="agents", method="patch", params="{id}", body="agent", resp="agent"),
        AgentDelete=dict(ep="agents", method="delete", params="{id}"),
        TestsList=dict(ep="tests", method="get", resp="tests"),
        TestGet=dict(ep="tests", method="get", params="{id}", resp="test"),
        TestCreate=dict(ep="tests", method="post", body="test", resp="test"),
        TestDelete=dict(ep="tests", method="delete", params="{id}"),
        TestPatch=dict(ep="tests", method="patch", params="{id}", body="test", resp="test"),
        TestStatusUpdate=dict(ep="tests", method="put", params="{id}/status", body="test_status"),
        GetHealthForTests=dict(ep="health", method="post", body="health_request", resp="health"),
        GetTraceForTest=dict(ep="health", method="post", params="{id}/results/trace", body="trace_request", resp="*"),
    )
    END_POINTS = dict(
        agents="/synthetics/v202101beta1/agents",
        tests="/synthetics/v202101beta1/tests",
        health="/synthetics/v202101beta1/health/tests",
    )

    def __init__(self, credentials: Tuple[str, str], url: str = "https://synthetics.api.kentik.com"):
        # noinspection PyProtectedMember
        self._session = KentikAPI(*credentials).query._api_connector._session
        self._url = url
        self._methods = dict(
            get=self._session.get,
            put=self._session.put,
            post=self._session.post,
            patch=self._session.patch,
            delete=self._session.delete,
        )

    def _ep(self, fn: str, path: Optional[str] = None) -> str:
        try:
            p = self._url + self.END_POINTS[fn]
            if path:
                return "/".join([p, path])
            else:
                return p
        except KeyError:
            raise RuntimeError(f"No end-point for function '{fn}'")

    def req(self, op: str, **kwargs) -> Any:
        try:
            svc = self.OPS[op]
        except KeyError:
            raise RuntimeError(f"Invalid operation '{op}'")
        try:
            method = self._methods[svc["method"]]
        except KeyError as ex:
            raise RuntimeError(f"Invalid method ({ex}) for operation '{op}'")
        params = svc.get("params")
        if params:
            try:
                path = params.format(**kwargs)
                log.debug("path: %s", path)
            except KeyError as ex:
                raise RuntimeError(f"Missing required parameter '{ex}' for operation '{op}'")
        else:
            path = None
        url = self._ep(svc["ep"], path)
        log.debug("url: %s", url)
        if svc.get("body"):
            try:
                json = kwargs["body"]
            except KeyError as ex:
                raise RuntimeError(f"'{ex}' is required for '{op}'")
            log.debug("body: %s", " ".join([f"{k}:{v}" for k, v in json.items()]))
        else:
            json = None
        r = method(url, json=json)
        if r.status_code not in self.HTTP_SUCCESS_CODES:
            raise KentikAPIRequestError(
                status=r.status_code,
                message=f"{svc['method'].upper()} failed - status: {r.status_code} error: {r.content}",
                response=r,
            )
        resp = svc.get("resp")
        if resp:
            if resp == "*":
                return r.json()
            else:
                return r.json()[resp]
        else:
            return None
