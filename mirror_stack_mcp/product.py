"""Independent product entrypoint; no consumer application dependency."""
import os
from .workspace import Workspace

workspace = Workspace(
    product="mirror-stack", prefix="MIRROR",
    control=".mirror-mcp-runtime", package="mirror_stack_mcp",
    modes={"observe":[],"record":["mm_preregister","mm_retract","am_record","am_witness","pm_verify"]}, defaults={"record":["am_record","text",""],"verify":["am_verify","ledger_path","actions.jsonl"]},
)

def root():
    value = os.environ.get("MIRROR_MCP_ROOT")
    if not value:
        raise ValueError("Use mirror-stack setup, then mirror-stack serve --workspace FOLDER.")
    return workspace.root(value)

def main():
    raise SystemExit(workspace.cli())

if __name__ == "__main__":
    main()
