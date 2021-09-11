import logging
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from .types import IPFamily, Protocol, TestStatus, TestType

log = logging.getLogger("synth_tests")


@dataclass
class Defaults:
    period: int = 60
    expiry: int = 5000
    family: IPFamily = IPFamily.dual


_ConfigElementType = TypeVar("_ConfigElementType", bound="_ConfigElement")


@dataclass
class _ConfigElement:
    def to_dict(self) -> dict:
        ret: Dict[str, dict] = dict()
        for k, v in [(f.name, self.__getattribute__(f.name)) for f in fields(self) if f.name[0] != "_"]:
            if hasattr(v, "to_dict"):
                ret[k] = v.to_dict()
            else:
                ret[k] = v
        return ret

    @classmethod
    def from_dict(cls: Type[_ConfigElementType], d: dict) -> _ConfigElementType:
        # noinspection PyProtectedMember
        def get_value(f, v):
            if hasattr(f, "from_dict"):
                return f.from_dict(v)
            else:
                try:
                    return f(v)
                except TypeError:
                    if f._name == "List":
                        return [get_value(type(i), i) for i in v]
                    elif f._name == "Dict":
                        return {_k: get_value(type(_v), _v) for _k, _v in v.items()}
                    else:
                        raise RuntimeError(f"Don't know how to instantiate '{f}' (value: '{v}')")

        _init_fields = {f.name: f for f in fields(cls) if f.init}
        args = {k: get_value(_init_fields[k].type, v) for k, v in d.items() if k in _init_fields.keys()}
        # noinspection PyArgumentList
        inst = cls(**args)  # type: ignore
        _other_fields = {f.name: f for f in fields(cls) if not f.init}
        for n, f in _other_fields.items():
            if n[0] == "_":
                k = n.split("_")[1]
            else:
                k = n
            if k in d:
                setattr(inst, n, get_value(f.type, d[k]))
        return inst


@dataclass
class PingTask(_ConfigElement):
    period: int = Defaults.period
    count: int = 5
    expiry: int = 3000


@dataclass
class TraceTask(_ConfigElement):
    period: int = Defaults.period
    count: int = 3
    protocol: Protocol = Protocol.icmp
    port: int = 0
    expiry: int = 22500
    limit: int = 30


@dataclass
class HTTPTask(_ConfigElement):
    period: int = 0
    expiry: int = 0
    method: str = "GET"
    headers: dict = field(default_factory=dict)
    body: str = ""
    ignoreTlsErrors: bool = False
    cssSelectors: dict = field(default_factory=dict)


class _DefaultList(list):
    _values: Tuple

    def __init__(self):
        super().__init__()
        for v in self._values:
            self.append(v)


class DefaultHTTPValidCodes(_DefaultList):
    _values = (200, 201)


class DefaultDNSValidCodes(_DefaultList):
    _values = (1, 2, 3)


@dataclass
class HealthSettings(_ConfigElement):
    latencyCritical: int = 0
    latencyWarning: int = 0
    packetLossCritical: int = 0
    packetLossWarning: int = 0
    jitterCritical: int = 0
    jitterWarning: int = 0
    httpLatencyCritical: int = 0
    httpLatencyWarning: int = 0
    httpValidCodes: List[int] = field(default_factory=list)
    dnsValidCodes: List[int] = field(default_factory=list)


class DefaultTasks(_DefaultList):
    _values = ("ping", "traceroute")


@dataclass
class MonitoringSettings(_ConfigElement):
    activationGracePeriod: str = "2"
    activationTimeUnit: str = "m"
    activationTimeWindow: str = "5"
    activationTimes: str = "3"
    notificationChannels: List = field(default_factory=list)


@dataclass
class SynTestSettings(_ConfigElement):
    agentIds: List[str] = field(default_factory=list)
    tasks: List[str] = field(default_factory=DefaultTasks)
    healthSettings: HealthSettings = field(default_factory=HealthSettings)
    monitoringSettings: MonitoringSettings = field(default_factory=MonitoringSettings)
    port: int = 0
    period: int = Defaults.period
    count: int = 0
    expiry: int = Defaults.expiry
    limit: int = 0
    protocol: Protocol = field(init=False, default=Protocol.none)
    family: IPFamily = Defaults.family
    rollupLevel: int = field(init=False, default=1)
    servers: List[str] = field(default_factory=list)


@dataclass
class SynTest(_ConfigElement):
    name: str
    type: TestType = field(init=False, default=TestType.none)
    status: TestStatus = field(default=TestStatus.active)
    deviceId: str = field(init=False, default="0")
    _id: str = field(default="0", init=False)
    _cdate: str = field(default_factory=str, init=False)
    _edate: str = field(default_factory=str, init=False)
    settings: SynTestSettings = field(default_factory=SynTestSettings)

    @property
    def id(self) -> str:
        return self._id

    @property
    def deployed(self) -> bool:
        return self.id != '0'

    @property
    def cdate(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self._cdate.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def edate(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self._edate.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def max_period(self) -> int:
        return max(
            [self.settings.period]
            + [self.settings.__getattribute__(t).period for t in self.settings.tasks if hasattr(self.settings, t)]
        )

    def to_dict(self) -> dict:
        return {"test": super(SynTest, self).to_dict()}

    @classmethod
    def test_from_dict(cls, d: dict):
        def class_for_type(test_type: TestType) -> Any:
            return {
                TestType.none: SynTest,
                TestType.hostname: HostnameTest,
                TestType.ip: IPTest,
                TestType.mesh: MeshTest,
                TestType.network_grid: NetworkGridTest,
                TestType.dns: DNSTest,
                TestType.dns_grid: DNSGridTest,
                TestType.page_load: PageLoadTest,
                TestType.agent: AgentTest,
                TestType.bgp_monitor: SynTest,
                TestType.url: UrlTest,
            }.get(test_type)

        try:
            cls_type = class_for_type(TestType(d["type"]))
        except KeyError as ex:
            raise RuntimeError(f"Required attribute '{ex}' missing in test data ('{d}')")
        if cls_type is None:
            raise RuntimeError(f"Unsupported test type: {d['type']}")
        if cls_type == cls:
            log.warning(
                "'%s' tests are not fully supported in the API. Test will have incomplete attributes", d["type"]
            )
        return cls_type.from_dict(d)

    def set_period(self, period_seconds: int, tasks: Optional[List[str]] = None):
        if not tasks:
            self.settings.period = period_seconds
        else:
            missing = []
            for task_name in tasks:
                try:
                    self.settings.__getattribute__(task_name).period = period_seconds
                except AttributeError:
                    missing.append(task_name)
            if missing:
                raise RuntimeError("tasks '{}' not presents in test '{}'".format(" ".join(missing), self.name))

    def set_timeout(self, timeout_seconds: float, tasks: Optional[List[str]] = None):
        if not tasks:
            self.settings.expiry = int(timeout_seconds * 1000)
        else:
            # sanity check
            missing = [t for t in tasks if t not in self.settings.tasks]
            if missing:
                raise RuntimeError("tasks '{}' not presents in test '{}'".format(" ".join(missing), self.name))
            for task_name in tasks:
                self.settings.__getattribute__(task_name).expiry = int(timeout_seconds * 1000)  # API wants it in millis


@dataclass
class PingTraceTestSettings(SynTestSettings):
    ping: PingTask = field(default_factory=PingTask)
    trace: TraceTask = field(default_factory=TraceTask)
    family: IPFamily = IPFamily.dual
    protocol: Protocol = Protocol.icmp


@dataclass
class PingTraceTest(SynTest):
    settings: PingTraceTestSettings = field(default_factory=PingTraceTestSettings)

    def set_period(self, period_seconds: int, tasks: Optional[List[str]] = None):
        if not tasks:
            tasks = [t for t in self.settings.tasks and hasattr(self.settings, t)]
        else:
            # sanity check
            missing = [t for t in tasks if not hasattr(self.settings, t)]
            if missing:
                raise RuntimeError("tasks '{}' not presents in test '{}'".format(" ".join(missing), self.name))
        for task_name in tasks:
            self.settings.__getattribute__(task_name).period = period_seconds

    def set_timeout(self, timeout_seconds: float, tasks: Optional[List[str]] = None):
        if not tasks:
            tasks = self.settings.tasks
        else:
            # sanity check
            missing = [t for t in tasks if t not in self.settings.tasks]
            if missing:
                raise RuntimeError("tasks '{}' not presents in test '{}'".format(" ".join(missing), self.name))
        for task_name in tasks:
            self.settings.__getattribute__(task_name).expiry = int(timeout_seconds * 1000)  # API wants it in millis


@dataclass
class HostnameTestSettings(PingTraceTestSettings):
    hostname: dict = field(default_factory=dict)


HostnameTestType = TypeVar("HostnameTestType", bound="HostnameTest")


@dataclass
class HostnameTest(PingTraceTest):
    type: TestType = field(init=False, default=TestType.hostname)
    settings: HostnameTestSettings = field(default_factory=HostnameTestSettings)

    @classmethod
    def create(cls: Type[HostnameTestType], name: str, target: str, agent_ids: List[str]) -> HostnameTestType:
        return cls(name=name, settings=HostnameTestSettings(agentIds=agent_ids, hostname=dict(target=target)))


@dataclass
class IPTestSettings(PingTraceTestSettings):
    ip: dict = field(default_factory=dict)


IPTestType = TypeVar("IPTestType", bound="IPTest")


@dataclass
class IPTest(PingTraceTest):
    type: TestType = field(init=False, default=TestType.ip)
    settings: IPTestSettings = field(default_factory=IPTestSettings)

    @classmethod
    def create(cls: Type[IPTestType], name: str, targets: List[str], agent_ids: List[str]) -> IPTestType:
        return cls(name=name, settings=IPTestSettings(agentIds=agent_ids, ip=dict(targets=targets)))


MeshTestType = TypeVar("MeshTestType", bound="MeshTest")


@dataclass
class MeshTest(PingTraceTest):
    type: TestType = field(init=False, default=TestType.mesh)

    @classmethod
    def create(cls: Type[MeshTestType], name: str, agent_ids: List[str]) -> MeshTestType:
        return cls(name=name, settings=PingTraceTestSettings(agentIds=agent_ids))


@dataclass
class GridTestSettings(PingTraceTestSettings):
    networkGrid: dict = field(default_factory=dict)


NetworkGridTestType = TypeVar("NetworkGridTestType", bound="NetworkGridTest")


@dataclass
class NetworkGridTest(PingTraceTest):
    type: TestType = field(init=False, default=TestType.network_grid)
    settings: GridTestSettings = field(default=GridTestSettings(agentIds=[]))

    @classmethod
    def create(
        cls: Type[NetworkGridTestType], name: str, targets: List[str], agent_ids: List[str]
    ) -> NetworkGridTestType:
        return cls(name=name, settings=GridTestSettings(agentIds=agent_ids, networkGrid=dict(targets=targets)))


@dataclass
class DNSGridTestSettings(SynTestSettings):
    dnsGrid: dict = field(default_factory=dict)


DNSGridTestType = TypeVar("DNSGridTestType", bound="DNSGridTest")


@dataclass
class DNSGridTest(SynTest):
    type: TestType = field(init=False, default=TestType.dns_grid)
    settings: DNSGridTestSettings = field(default_factory=DNSGridTestSettings)

    @classmethod
    def create(
        cls: Type[DNSGridTestType], name: str, targets: List[str], agent_ids: List[str], servers: List[str]
    ) -> DNSGridTestType:
        return cls(
            name=name,
            settings=DNSGridTestSettings(
                agentIds=agent_ids, dnsGrid=dict(targets=targets), servers=servers, tasks=["dns"], port=53
            ),
        )

    @property
    def max_period(self) -> int:
        return self.settings.period


@dataclass
class DNSTestSettings(SynTestSettings):
    dns: dict = field(default_factory=dict)


DNSTestType = TypeVar("DNSTestType", bound="DNSTest")


@dataclass
class DNSTest(SynTest):
    type: TestType = field(init=False, default=TestType.dns)
    settings: DNSTestSettings = field(default_factory=DNSTestSettings)

    @classmethod
    def create(cls: Type[DNSTestType], name: str, target: str, agent_ids: List[str], servers: List[str]) -> DNSTestType:
        return cls(
            name=name,
            settings=DNSTestSettings(
                agentIds=agent_ids, dns=dict(target=target), servers=servers, tasks=["dns"], port=53
            ),
        )

    @property
    def max_period(self) -> int:
        return self.settings.period


@dataclass
class UrlTestSettings(SynTestSettings):
    url: dict = field(default_factory=dict)
    ping: PingTask = field(default_factory=PingTask)
    trace: TraceTask = field(default_factory=TraceTask)
    http: HTTPTask = field(default_factory=HTTPTask)


UrlTestType = TypeVar("UrlTestType", bound="UrlTest")


@dataclass
class UrlTest(SynTest):
    type: TestType = field(init=False, default=TestType.url)
    settings: UrlTestSettings = field(default_factory=UrlTestSettings)

    @classmethod
    def create(
        cls: Type[UrlTestType],
        name: str,
        target: str,
        agent_ids: List[str],
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: str = "",
        ignore_tls_errors: bool = False,
        ping: bool = False,
        trace: bool = False,
    ) -> UrlTestType:
        tasks: List[str] = ["http"]
        if ping:
            tasks.append("ping")
        if trace:
            tasks.append("traceroute")
        return cls(
            name=name,
            settings=UrlTestSettings(
                agentIds=agent_ids,
                url=dict(target=target),
                tasks=tasks,
                http=HTTPTask(method=method, body=body, headers=headers or {}, ignoreTlsErrors=ignore_tls_errors),
            ),
        )


@dataclass
class PageLoadTestSettings(SynTestSettings):
    pageLoad: dict = field(default_factory=dict)
    http: HTTPTask = field(default_factory=HTTPTask)


PageLoadTestType = TypeVar("PageLoadTestType", bound="PageLoadTest")


@dataclass
class PageLoadTest(SynTest):
    type: TestType = field(init=False, default=TestType.page_load)
    settings: PageLoadTestSettings = field(default_factory=PageLoadTestSettings)

    @classmethod
    def create(
        cls: Type[PageLoadTestType],
        name: str,
        target: str,
        agent_ids: List[str],
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: str = "",
        ignore_tls_errors: bool = False,
    ) -> PageLoadTestType:
        return cls(
            name=name,
            settings=PageLoadTestSettings(
                agentIds=agent_ids,
                pageLoad=dict(target=target),
                tasks=["page-load"],
                http=HTTPTask(method=method, body=body, headers=headers or {}, ignoreTlsErrors=ignore_tls_errors),
            ),
        )


@dataclass
class AgentTestSettings(PingTraceTestSettings):
    agent: dict = field(default_factory=dict)


AgentTestType = TypeVar("AgentTestType", bound="AgentTest")


@dataclass
class AgentTest(PingTraceTest):
    type: TestType = field(init=False, default=TestType.agent)
    settings: AgentTestSettings = field(default=AgentTestSettings(agentIds=[]))

    @classmethod
    def create(cls: Type[AgentTestType], name: str, target: str, agent_ids: List[str]) -> AgentTestType:
        return cls(name=name, settings=AgentTestSettings(agentIds=agent_ids, agent=dict(target=target)))


def dict_compare(left: dict, right: dict, path: str = "") -> List[str]:
    diffs = []
    if path is None:
        path = []
    a_keys = set(left.keys())
    b_keys = set(right.keys())
    for k in a_keys.difference(right.keys()):
        diffs.append(f"{path}: {k} not in right")
    for k in b_keys.difference(left.keys()):
        diffs.append(f"{path}: {k} not in left")
    for k, vl, vr in [(_k, _v, right[_k]) for _k, _v in left.items() if _k in right]:
        if not isinstance(vl, type(vr)) and not isinstance(vr, type(vl)):
            diffs.append(f"{path}.{k}: incompatible types (left: {type(vl)} right: {type(vr)})")
        else:
            if isinstance(vl, dict):
                diffs.extend(dict_compare(vl, vr, f"{path}.{k}"))
            else:
                if vl != vr:
                    diffs.append(f"{path}.{k}: different value (left: {vl} right: {vr})")
    return diffs


def compare_tests(left: SynTest, right: SynTest) -> List[str]:
    return dict_compare(left.to_dict(), right.to_dict())
