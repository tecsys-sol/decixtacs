"""Import a classic Shrubbery ``tac_plus`` (F4.0.4.x) configuration into NetworkOps Manager.

Parses ``key``, ``host``, ``group`` and ``user`` blocks and turns them into portal objects:

* ``key`` / ``host = X { key = … }``  -> NAS clients (existing shared keys kept, so devices need no change)
* ``group``                            -> platform group + TACACS policy (inherited attributes flattened)
* ``user``                             -> platform user + TACACS user mapping; ``des``/crypt hashes are
                                          kept as-is, ``cleartext`` passwords are re-hashed (SHA-512)
* ``service = exec|shell|junos-exec|fortigate { … }`` -> privilege level / Junos class / FortiGate
  admin profile / vendor attributes
* ``cmd = X { permit|deny regex … }`` -> ordered command rules on the full command line

Anything that cannot be represented is reported as a warning instead of being silently dropped.
The same plan is used for the dry-run preview and the real import.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# --- tokenizer ------------------------------------------------------------------------------------

_PUNCT = "{}="


class ParseError(ValueError):
    pass


def tokenize(text: str) -> list[tuple[str, int]]:
    """Return (token, line) pairs. Quoted strings keep their content; ``#`` starts a comment."""
    out: list[tuple[str, int]] = []
    i, line, n = 0, 1, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif c == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif c in _PUNCT:
            out.append((c, line))
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == "\n":
                    line += 1
                buf.append(text[i])
                i += 1
            if i >= n:
                raise ParseError(f"line {line}: unterminated string")
            i += 1
            out.append(("\x00" + "".join(buf), line))  # \x00 marks a quoted string
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in _PUNCT and text[i] != "#":
                i += 1
            out.append((text[start:i], line))
    return out


def _val(tok: str) -> str:
    return tok[1:] if tok.startswith("\x00") else tok


# --- AST --------------------------------------------------------------------------------------------


@dataclass
class CmdBlock:
    name: str
    rules: list[tuple[str, str]] = field(default_factory=list)  # (permit|deny, regex)


@dataclass
class Entity:
    kind: str  # user | group
    name: str
    line: int
    members: list[str] = field(default_factory=list)
    login: tuple[str, str | None] | None = None  # (method, value)
    full_name: str | None = None
    expires: str | None = None
    default_service_permit: bool | None = None
    services: dict[str, dict[str, str]] = field(default_factory=dict)
    cmds: list[CmdBlock] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


@dataclass
class HostEntry:
    address: str
    key: str | None
    line: int


@dataclass
class ParsedConfig:
    key: str | None = None
    hosts: list[HostEntry] = field(default_factory=list)
    groups: dict[str, Entity] = field(default_factory=dict)
    users: dict[str, Entity] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class _Parser:
    def __init__(self, text: str):
        self.toks = tokenize(text)
        self.i = 0

    def peek(self, k: int = 0) -> str | None:
        j = self.i + k
        return self.toks[j][0] if j < len(self.toks) else None

    def line(self) -> int:
        return self.toks[min(self.i, len(self.toks) - 1)][1] if self.toks else 0

    def next(self) -> str:
        if self.i >= len(self.toks):
            raise ParseError("unexpected end of file")
        tok = self.toks[self.i][0]
        self.i += 1
        return tok

    def expect(self, tok: str) -> None:
        got = self.next()
        if got != tok:
            raise ParseError(f"line {self.toks[self.i - 1][1]}: expected '{tok}', got '{_val(got)}'")

    def skip_block(self) -> None:
        """Skip a balanced ``{ … }`` block (current token must be '{')."""
        self.expect("{")
        depth = 1
        while depth:
            t = self.next()
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1

    def skip_value_or_block(self) -> None:
        if self.peek() == "{":
            self.skip_block()
            return
        self.next()
        if self.peek() == "{":
            self.skip_block()

    def parse(self) -> ParsedConfig:
        cfg = ParsedConfig()
        while self.peek() is not None:
            line = self.line()
            word = _val(self.next())
            if word == "key":
                self.expect("=")
                cfg.key = _val(self.next())
            elif word == "host":
                self.expect("=")
                addr = _val(self.next())
                key = None
                if self.peek() == "{":
                    self.next()
                    while self.peek() != "}":
                        attr = _val(self.next())
                        if attr == "key":
                            self.expect("=")
                            key = _val(self.next())
                        else:
                            if self.peek() == "=":
                                self.next()
                            self.skip_value_or_block()
                            cfg.warnings.append(f"line {line}: host {addr}: '{attr}' ignored")
                    self.next()
                cfg.hosts.append(HostEntry(addr, key, line))
            elif word in ("user", "group"):
                self.expect("=")
                name = _val(self.next())
                ent = self.parse_entity(word, name, line)
                target = cfg.users if word == "user" else cfg.groups
                if name in target:
                    cfg.warnings.append(f"line {line}: duplicate {word} '{name}' - later definition wins")
                target[name] = ent
            elif word == "accounting" or word == "logging":
                # accounting file = …, logging = …
                while self.peek() not in (None, "="):
                    self.next()
                if self.peek() == "=":
                    self.next()
                    self.next()
                cfg.warnings.append(f"line {line}: '{word}' setting ignored (the platform manages logging)")
            elif word == "default":
                # default authentication = file /etc/passwd
                while self.peek() != "=":
                    self.next()
                self.next()
                val = [_val(self.next())]
                if val[0] in ("file", "skey"):
                    val.append(_val(self.next()))
                cfg.warnings.append(
                    f"line {line}: 'default authentication = {' '.join(val)}' is not supported; "
                    "users without a password must be given one or use LDAP"
                )
            elif word == "acl":
                self.expect("=")
                name = _val(self.next())
                if self.peek() == "{":
                    self.skip_block()
                cfg.warnings.append(
                    f"line {line}: acl '{name}' (source-address restriction) is not supported "
                    "and was ignored - scope policies by device group instead"
                )
            else:
                raise ParseError(f"line {line}: unknown top-level directive '{word}'")
        return cfg

    def parse_entity(self, kind: str, name: str, line: int) -> Entity:
        ent = Entity(kind, name, line)
        self.expect("{")
        while True:
            t = self.peek()
            if t is None:
                raise ParseError(f"{kind} '{name}' (line {line}): missing '}}'")
            if t == "}":
                self.next()
                return ent
            aline = self.line()
            attr = _val(self.next())
            if attr == "default":
                what = _val(self.next())  # service
                self.expect("=")
                val = _val(self.next())
                if what == "service":
                    ent.default_service_permit = val == "permit"
                else:
                    ent.ignored.append(f"default {what}")
            elif attr == "member":
                self.expect("=")
                ent.members.append(_val(self.next()))
            elif attr == "name":
                self.expect("=")
                ent.full_name = _val(self.next())
            elif attr == "expires":
                self.expect("=")
                ent.expires = _val(self.next())
            elif attr == "login":
                self.expect("=")
                method = _val(self.next())
                value = None
                if method in ("des", "cleartext", "file", "skey", "crypt"):
                    value = _val(self.next())
                ent.login = (method, value)
            elif attr == "service":
                self.expect("=")
                svc = _val(self.next())
                # ppp style: service = ppp protocol = ip { … }
                while self.peek() not in ("{", None):
                    self.next()
                attrs: dict[str, str] = {}
                self.expect("{")
                while self.peek() != "}":
                    k = _val(self.next())
                    if k == "optional":
                        k = _val(self.next())
                    self.expect("=")
                    attrs[k] = _val(self.next())
                self.next()
                ent.services[svc] = {**ent.services.get(svc, {}), **attrs}
            elif attr == "cmd":
                self.expect("=")
                block = CmdBlock(_val(self.next()))
                self.expect("{")
                while self.peek() != "}":
                    action = _val(self.next())
                    if action not in ("permit", "deny"):
                        raise ParseError(f"line {aline}: expected permit/deny in cmd block, got '{action}'")
                    block.rules.append((action, _val(self.next())))
                self.next()
                ent.cmds.append(block)
            elif attr in ("enable", "pap", "chap", "arap", "opap", "ms-chap", "global", "acl"):
                if self.peek() == "=":
                    self.next()
                method = _val(self.next())
                if method in ("des", "cleartext", "file", "skey", "crypt"):
                    self.next()
                ent.ignored.append(attr)
            elif attr in ("before", "after"):
                # before authorization = "/path/script"
                self.next()
                self.expect("=")
                self.next()
                ent.ignored.append(f"{attr} authorization")
            else:
                raise ParseError(f"line {aline}: unknown attribute '{attr}' in {kind} '{name}'")


def parse(text: str) -> ParsedConfig:
    return _Parser(text).parse()


# --- conversion -------------------------------------------------------------------------------------

_JUNOS_KEYS = {
    "local-user-name",
    "allow-commands",
    "deny-commands",
    "allow-configuration",
    "deny-configuration",
    "allow-configuration-regexps",
    "deny-configuration-regexps",
}


@dataclass
class PlannedPolicy:
    name: str
    group: str
    priority: int
    privilege_level: int
    default_action: str
    junos_class: str | None
    fortigate_profile: str | None
    extra_attributes: dict[str, dict[str, str]]
    rules: list[tuple[str, str]]  # (action, full-command regex)


@dataclass
class PlannedUser:
    username: str
    full_name: str | None
    groups: list[str]
    password_crypt: str | None
    cleartext: str | None
    valid_until: datetime | None
    note: str | None = None


@dataclass
class PlannedNas:
    name: str
    address: str
    key: str


@dataclass
class ImportPlan:
    nas: list[PlannedNas]
    groups: list[str]
    policies: list[PlannedPolicy]
    users: list[PlannedUser]
    warnings: list[str]


def cmd_regex(cmd: str, arg_regex: str) -> str:
    """Shrubbery matches ``arg_regex`` (unanchored) against the argument string of ``cmd``.
    tac_plus-ng matches one regex against the whole command line, so combine them."""
    head = "^" + re.escape(cmd)
    a = arg_regex.strip()
    if a in (".*", "", "^.*", "^.*$"):
        return head + "( |$)"
    if a.startswith("^"):
        return head + " " + a[1:]
    return head + " .*(" + a + ")"


def _parse_expires(value: str) -> datetime | None:
    for fmt in ("%b %d %Y", "%B %d %Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.strptime(" ".join(value.split()), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "x"


def build_plan(cfg: ParsedConfig) -> ImportPlan:
    warnings = list(cfg.warnings)

    # --- NAS clients
    nas: list[PlannedNas] = []
    seen_addr: set[str] = set()
    for h in cfg.hosts:
        key = h.key or cfg.key
        if not key:
            warnings.append(f"line {h.line}: host {h.address} has no key and there is no global key - skipped")
            continue
        try:
            net = ipaddress.ip_network(h.address, strict=False)
            addr = str(net.network_address) if net.num_addresses == 1 else str(net)
        except ValueError:
            warnings.append(
                f"line {h.line}: host '{h.address}' is not an IP address/prefix - skipped "
                "(add it as a NAS client with its IP)"
            )
            continue
        if addr in seen_addr:
            continue
        seen_addr.add(addr)
        nas.append(PlannedNas(f"nas-{_slug(addr.replace('/', '_'))}", addr, key))
    if cfg.key:
        nas.append(PlannedNas("default-any-v4", "0.0.0.0/0", cfg.key))
        nas.append(PlannedNas("default-any-v6", "::/0", cfg.key))
        warnings.append(
            "the global 'key' became catch-all NAS clients 0.0.0.0/0 and ::/0 (every device using the "
            "global key keeps working); narrow them to your management prefixes after the cut-over"
        )

    # --- groups: resolve inheritance
    def ancestors(name: str, trail: tuple[str, ...] = ()) -> list[str]:
        g = cfg.groups.get(name)
        if g is None:
            return []
        out: list[str] = []
        for parent in g.members:
            if parent in trail or parent == name:
                warnings.append(f"group membership loop at '{name}' -> '{parent}' - ignored")
                continue
            if parent not in cfg.groups:
                warnings.append(f"group '{name}' is member of undefined group '{parent}'")
                continue
            out.append(parent)
            out.extend(a for a in ancestors(parent, (*trail, name)) if a not in out)
        return out

    def effective(ents: list[Entity]) -> tuple[int, str, str | None, str | None, dict, list[tuple[str, str]]]:
        """Merge entities, most specific first (earlier entries win)."""
        priv: int | None = None
        default_permit = next((e.default_service_permit for e in ents if e.default_service_permit is not None), False)
        junos: dict[str, str] = {}
        forti: dict[str, str] = {}
        shell_extra: dict[str, str] = {}
        rules: list[tuple[str, str]] = []
        for e in ents:
            for svc, attrs in e.services.items():
                if svc in ("exec", "shell"):
                    for k, v in attrs.items():
                        if k == "priv-lvl":
                            if priv is None and v.isdigit():
                                priv = int(v)
                        else:
                            shell_extra.setdefault(k, v)
                elif svc == "junos-exec":
                    for k, v in attrs.items():
                        junos.setdefault(k, v)
                elif svc == "fortigate":
                    for k, v in attrs.items():
                        forti.setdefault(k, v)
                else:
                    warnings.append(f"{e.kind} '{e.name}': service '{svc}' is not supported and was ignored")
            for block in e.cmds:
                for action, rx in block.rules:
                    rules.append((action, cmd_regex(block.name, rx)))
                # Shrubbery: a cmd that is listed but whose arguments match no rule is denied. Only needed
                # when unmatched commands would otherwise be permitted.
                if default_permit:
                    rules.append(("deny", cmd_regex(block.name, ".*")))
        default_action = "permit" if default_permit else "deny"
        extra: dict[str, dict[str, str]] = {}
        junos_class = junos.pop("local-user-name", None)
        if junos:
            extra["juniper"] = junos
            if rules:
                warnings.append(
                    f"'{ents[0].name}': Junos allow/deny-commands attributes are sent in addition to "
                    "the converted cmd rules - review the policy"
                )
        forti_prof = forti.pop("admin_prof", None)
        if forti:
            extra["fortinet"] = forti
        if shell_extra:
            extra["shell"] = shell_extra
        seen: set[tuple[str, str]] = set()
        rules = [r for r in rules if not (r in seen or seen.add(r))]
        return priv if priv is not None else 1, default_action, junos_class, forti_prof, extra, rules

    policies: list[PlannedPolicy] = []
    groups: list[str] = []
    for name, g in cfg.groups.items():
        anc = ancestors(name)
        chain = [g] + [cfg.groups[a] for a in anc]
        priv, dflt, jc, fp, extra, rules = effective(chain)
        groups.append(name)
        policies.append(
            PlannedPolicy(f"imp-{_slug(name)}", name, 200 - 10 * min(len(anc), 9), priv, dflt, jc, fp, extra, rules)
        )
        if g.ignored:
            warnings.append(f"group '{name}': {', '.join(sorted(set(g.ignored)))} ignored")

    users: list[PlannedUser] = []
    for name, u in cfg.users.items():
        direct = [m for m in u.members if m in cfg.groups]
        for m in u.members:
            if m not in cfg.groups:
                warnings.append(f"user '{name}' is member of undefined group '{m}'")
        all_groups: list[str] = []
        for m in direct:
            for gname in [m, *ancestors(m)]:
                if gname not in all_groups:
                    all_groups.append(gname)
        crypt_hash = cleartext = note = None
        if u.login is None:
            note = "no login password in the old config - set one or use LDAP"
        else:
            method, value = u.login
            if method in ("des", "crypt") and value:
                crypt_hash = value
            elif method == "cleartext" and value is not None:
                cleartext = value
            elif method == "file":
                note = f"login = file {value}: authenticated against a local passwd file - set a password or use LDAP"
            elif method.upper() == "PAM":
                note = "login = PAM: authenticated by the TACACS host - set a password or use LDAP"
            else:
                note = f"login = {method} is not supported - set a password or use LDAP"
        if note:
            warnings.append(f"user '{name}': {note}")
        if u.ignored:
            warnings.append(f"user '{name}': {', '.join(sorted(set(u.ignored)))} ignored")
        valid_until = None
        if u.expires:
            valid_until = _parse_expires(u.expires)
            if valid_until is None:
                warnings.append(f"user '{name}': unparseable expires '{u.expires}' ignored")
        # user-level authorization -> a personal group + policy that wins over group policies
        if u.services or u.cmds or u.default_service_permit is not None:
            personal = f"user-{_slug(name)}"
            chain = [u] + [cfg.groups[g] for g in all_groups]
            priv, dflt, jc, fp, extra, rules = effective(chain)
            groups.append(personal)
            policies.append(PlannedPolicy(f"imp-{personal}", personal, 50, priv, dflt, jc, fp, extra, rules))
            all_groups.insert(0, personal)
        users.append(PlannedUser(name, u.full_name, all_groups, crypt_hash, cleartext, valid_until, note))
    return ImportPlan(nas, groups, policies, users, warnings)
