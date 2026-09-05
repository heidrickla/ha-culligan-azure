"""Local stand-in for the checks CI would run.

hassfest and the HACS action run on GitHub; this approximates the parts of
them that can be checked with no network at all, plus the cross-file
consistency that nothing else checks: translation keys against icons,
exceptions raised against exceptions declared, actions registered against
actions described, the quality scale against the pinned rule list. Run it
before a push so the push is not the first verification.

    python tools/validate_local.py
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from typing import Any

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOMAIN = "culligan_azure"
COMP = os.path.join(ROOT, "custom_components", DOMAIN)
PLATFORMS = ("binary_sensor", "button", "number", "sensor", "switch")

# hassfest requires these for a custom integration.
REQUIRED_MANIFEST = [
    "domain",
    "name",
    "documentation",
    "codeowners",
    "iot_class",
    "version",
]
VALID_IOT_CLASS = {
    "assumed_state",
    "cloud_polling",
    "cloud_push",
    "local_polling",
    "local_push",
    "calculated",
}

# Home Assistant exceptions whose message reaches the user, so every raise
# must carry a translation key rather than an English f-string.
TRANSLATED_EXCEPTIONS = {
    "ConfigEntryAuthFailed",
    "ConfigEntryError",
    "ConfigEntryNotReady",
    "HomeAssistantError",
    "ServiceValidationError",
    "UpdateFailed",
}

# Pinned from developers.home-assistant.io/docs/core/integration-quality-scale/checklist
# (checked 2026-09-02: 54 rules, none new or deprecated). The list is pinned
# here on purpose: a quality_scale.yaml that is missing a rule reads as
# complete, and checking against the full list turns an omission into a
# failure.
ALL_RULES = {
    # Bronze
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    # Gold
    "devices",
    "diagnostics",
    "discovery-update-info",
    "discovery",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    # Platinum
    "async-dependency",
    "inject-websession",
    "strict-typing",
}

failures: list[str] = []
notes: list[str] = []


def read(*parts: str) -> str:
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def read_json(*parts: str) -> Any:
    return json.loads(read(*parts))


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def constants(source: str, prefix: str) -> dict[str, str]:
    """Module-level string assignments whose name starts with prefix."""
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id.startswith(prefix)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[target.id] = node.value.value
    return found


def untranslated_raises(source: str) -> list[str]:
    """Raises of user-facing Home Assistant exceptions with no translation key."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in TRANSLATED_EXCEPTIONS:
            continue
        keywords = {kw.arg for kw in node.exc.keywords}
        if "translation_domain" not in keywords or "translation_key" not in keywords:
            found.append(f"{name} at line {node.lineno}")
    return found


def main() -> int:
    manifest = read_json(COMP, "manifest.json")
    const_src = read(COMP, "const.py")
    strings = read_json(COMP, "strings.json")

    # ---------------------------------------------------------- manifest
    for key in REQUIRED_MANIFEST:
        check(key in manifest, f"manifest.json missing required key {key!r}")
    check(
        manifest.get("domain") == DOMAIN,
        f"manifest domain is {manifest.get('domain')!r}",
    )
    check(
        manifest.get("iot_class") in VALID_IOT_CLASS,
        f"manifest iot_class {manifest.get('iot_class')!r} is not a valid value",
    )
    check(
        isinstance(manifest.get("codeowners"), list)
        and all(c.startswith("@") for c in manifest["codeowners"]),
        "manifest codeowners entries must start with @",
    )
    keys = list(manifest)
    check(
        keys[:2] == ["domain", "name"] and keys[2:] == sorted(keys[2:]),
        "manifest keys must be domain, name, then alphabetical (hassfest MANIFEST)",
    )
    if re.search(
        r"//(?:localhost|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)",
        manifest.get("documentation", ""),
    ):
        notes.append("documentation URL points at a LAN host - useless to a user")
    check(
        "quality_scale" not in manifest,
        "quality_scale in manifest.json: the badge is core-only, a custom "
        "integration builds to the rules and does not claim a tier",
    )

    const_version = constants(const_src, "VERSION").get("VERSION")
    check(
        const_version == manifest.get("version"),
        f"const.VERSION {const_version!r} != manifest version "
        f"{manifest.get('version')!r} - HA reports one and HACS the other",
    )

    # pyproject carries no [project] table today; if one is added its version
    # must not drift from the manifest.
    pyproject_path = os.path.join(ROOT, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        try:
            import tomllib

            project = tomllib.loads(read(pyproject_path)).get("project", {})
            if "version" in project:
                check(
                    project["version"] == manifest.get("version"),
                    f"pyproject version {project['version']!r} != manifest "
                    f"{manifest.get('version')!r}",
                )
        except ImportError:
            notes.append("tomllib unavailable - pyproject version not compared")

    # ---------------------------------------------------------- hacs.json
    hacs = read_json(ROOT, "hacs.json")
    check("name" in hacs, "hacs.json must contain name")
    # The brand images ship only in-repo, which Home Assistant honours from
    # 2026.3.0; an older floor advertises installs that show a placeholder.
    floor = str(hacs.get("homeassistant", "0"))
    check(
        tuple(int(p) for p in floor.split(".")[:2]) >= (2026, 3),
        f"hacs.json homeassistant floor {floor} is below 2026.3.0, the first "
        "release that serves in-repo brand images",
    )

    # ---------------------------------------------------------- brand images
    brand = os.path.join(COMP, "brand")
    for name in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png"):
        check(os.path.isfile(os.path.join(brand, name)), f"missing brand/{name}")

    # ---------------------------------------------------------- translations
    en = read_json(COMP, "translations", "en.json")
    check(
        strings == en,
        "strings.json and translations/en.json differ - copy strings.json over",
    )

    # ---------------------------------------------------------- actions
    services_yaml = os.path.join(COMP, "services.yaml")
    check(os.path.isfile(services_yaml), "services.yaml is missing")
    service_consts = set(constants(const_src, "SERVICE_").values())
    declared_services = set(strings.get("services", {}))
    check(
        declared_services == service_consts,
        f"strings.json describes {sorted(declared_services)} but const.py "
        f"registers {sorted(service_consts)}",
    )
    try:
        import yaml

        services = yaml.safe_load(read(services_yaml)) or {}
        check(
            set(services) == service_consts,
            f"services.yaml declares {sorted(services)} but const.py registers "
            f"{sorted(service_consts)}",
        )
        for name, spec in services.items():
            yaml_fields = set((spec or {}).get("fields", {}))
            described = set(strings.get("services", {}).get(name, {}).get("fields", {}))
            check(
                yaml_fields == described,
                f"action {name}: services.yaml fields {sorted(yaml_fields)} != "
                f"strings.json fields {sorted(described)}",
            )
            for field_spec in (spec or {}).get("fields", {}).values():
                selector = (field_spec or {}).get("selector", {})
                tkey = (selector.get("select") or {}).get("translation_key")
                if tkey:
                    check(
                        tkey in strings.get("selector", {}),
                        f"selector translation {tkey!r} missing from strings.json",
                    )
    except ImportError:
        notes.append("PyYAML not installed - services.yaml not parsed")

    # ---------------------------------------------------------- quality scale
    scale_path = os.path.join(COMP, "quality_scale.yaml")
    scale_rules: dict[str, Any] = {}
    check(os.path.isfile(scale_path), "quality_scale.yaml is missing")
    if os.path.isfile(scale_path):
        try:
            import yaml

            declared = yaml.safe_load(read(scale_path)).get("rules", {})
            scale_rules = declared
            missing = ALL_RULES - set(declared)
            check(not missing, f"quality_scale.yaml does not mention {sorted(missing)}")
            unknown = set(declared) - ALL_RULES
            check(not unknown, f"quality_scale.yaml invents rules {sorted(unknown)}")
            for rule, value in sorted(declared.items()):
                if isinstance(value, dict):
                    check(
                        value.get("status") in {"done", "todo", "exempt"},
                        f"{rule}: status must be done/todo/exempt",
                    )
                    if value.get("status") != "done":
                        check(
                            bool(str(value.get("comment", "")).strip()),
                            f"{rule}: a non-done status needs a comment saying why",
                        )
                else:
                    check(value == "done", f"{rule}: bare value must be 'done'")
            todo = sorted(
                r
                for r, v in declared.items()
                if isinstance(v, dict) and v.get("status") == "todo"
            )
            if todo:
                notes.append(f"quality scale still todo: {', '.join(todo)}")
        except ImportError:
            notes.append("PyYAML not installed - quality_scale.yaml not parsed")

    # ------------------------------------------------------ icon translations
    # Every translation key an entity uses needs a name, and every name needs
    # an entity using it. Icons are a subset: an entity with a device class
    # takes the class icon and declares none.
    icons = read_json(COMP, "icons.json")
    key_re = re.compile(r'(?:_attr_translation_key\s*=|\btranslation_key=)\s*"([^"]+)"')
    exc_re = re.compile(r'translation_domain=DOMAIN,\s*translation_key="([^"]+)"')
    for platform in PLATFORMS:
        source = read(COMP, f"{platform}.py")
        used = set(key_re.findall(source)) - set(exc_re.findall(source))
        declared_icons = set(icons.get("entity", {}).get(platform, {}))
        named = set(strings.get("entity", {}).get(platform, {}))
        check(
            declared_icons <= used,
            f"{platform}: icons {sorted(declared_icons - used)} name no entity",
        )
        check(used == named, f"{platform}: names {sorted(named ^ used)} out of step")
    service_icons = set(icons.get("services", {}))
    check(
        service_icons == service_consts,
        f"icons.json services {sorted(service_icons)} != {sorted(service_consts)}",
    )

    # ------------------------------------------------- exception translations
    raised: set[str] = set()
    for f in sorted(os.listdir(COMP)):
        if f.endswith(".py"):
            source = read(COMP, f)
            raised |= set(exc_re.findall(source))
            for where in untranslated_raises(source):
                failures.append(f"{f}: {where} is raised without a translation key")
    declared_exc = set(strings.get("exceptions", {}))
    check(
        raised <= declared_exc,
        f"code raises undeclared exception keys {sorted(raised - declared_exc)}",
    )
    check(
        declared_exc <= raised,
        f"strings.json declares unused exceptions {sorted(declared_exc - raised)}",
    )

    # ----------------------------------------------------- issue translations
    issue_consts = set(constants(const_src, "ISSUE_").values())
    declared_issues = set(strings.get("issues", {}))
    check(
        issue_consts == declared_issues,
        f"const.py issues {sorted(issue_consts)} != strings.json issues "
        f"{sorted(declared_issues)}",
    )

    # ------------------------------------------------------------ platforms
    init_src = read(COMP, "__init__.py")
    for platform in PLATFORMS:
        check(
            f"Platform.{platform.upper()}" in init_src,
            f"{platform}.py exists but Platform.{platform.upper()} is not forwarded",
        )
        check(
            "PARALLEL_UPDATES" in read(COMP, f"{platform}.py"),
            f"{platform}.py does not set PARALLEL_UPDATES",
        )
    check("CONFIG_SCHEMA" in init_src, "__init__.py declares no CONFIG_SCHEMA")

    # ------------------------------------------------- quality scale mechanisms
    # A rule filed `done` whose mechanism is not in the file set is the failure
    # mode this whole file exists for: the yaml reads finished and nothing
    # contradicts it. Each entry is (rule, the mechanism is present, why not).
    repairs_src = (
        read(COMP, "repairs.py")
        if os.path.isfile(os.path.join(COMP, "repairs.py"))
        else ""
    )
    sensor_src = read(COMP, "sensor.py")
    workflow = os.path.join(ROOT, ".github", "workflows", "tests.yml")
    workflow_src = read(workflow) if os.path.isfile(workflow) else ""
    pyproject_src = read(pyproject_path) if os.path.isfile(pyproject_path) else ""

    mechanisms: list[tuple[str, bool, str]] = [
        (
            "repair-issues",
            bool(repairs_src)
            and "async_create_fix_flow" in repairs_src
            and bool(issue_consts)
            and "repairs" in manifest.get("dependencies", []),
            "needs repairs.py with async_create_fix_flow, an ISSUE_ constant "
            "and 'repairs' in manifest dependencies",
        ),
        (
            "stale-devices",
            "async_remove_config_entry_device" in init_src
            and "async_track_stale_devices" in init_src,
            "needs async_remove_config_entry_device and removal tracked on "
            "every poll, not only at setup",
        ),
        (
            "entity-device-class",
            "SensorDeviceClass.DURATION" in sensor_src
            and "SensorDeviceClass.VOLUME_STORAGE" in sensor_src,
            "the time and volume sensors carry no device class",
        ),
        (
            "test-coverage",
            "--cov-fail-under=95" in workflow_src,
            "the Tests workflow reports coverage without gating on it",
        ),
        (
            "strict-typing",
            "strict = true" in pyproject_src
            and "ignore_missing_imports" not in pyproject_src,
            "pyproject must set mypy strict with no ignore_missing_imports",
        ),
    ]
    for rule, present, why in mechanisms:
        value = scale_rules.get(rule)
        status = value.get("status") if isinstance(value, dict) else value
        if status == "done":
            check(present, f"{rule} is filed done but {why}")

    # ---------------------------------------------------------- shipped files
    check(
        not os.path.isfile(os.path.join(COMP, "README.md")),
        "a README inside the component folder ships to every user and drifts "
        "from the root README - keep one",
    )

    # ---------------------------------------------------------- syntax
    for dirpath, _dirs, files in os.walk(COMP):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(dirpath, f)
                try:
                    ast.parse(read(path))
                except SyntaxError as err:
                    failures.append(f"{f}: {err}")

    # ---------------------------------------------------------- report
    print(f"manifest {manifest.get('domain')} {manifest.get('version')}")
    for n in notes:
        print(f"  NOTE   {n}")
    for f in failures:
        print(f"  FAIL   {f}")
    if not failures:
        print("  all offline checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
