"""
Clone command module - Git repository operations
"""

from pathlib import Path
from typing import Optional
from fabric import Connection
from rich.console import Console

console = Console()


def clone_repository(
    conn: Connection,
    repo_url: str,
    workspace_dir: str,
    folder_name: Optional[str] = None,
    branch: str = "main",
    token: Optional[str] = None
) -> Optional[str]:
    """
    Clone a git repository to the workspace

    Args:
        conn: Fabric SSH connection
        repo_url: Git repository URL
        workspace_dir: Workspace directory path
        folder_name: Optional folder name for clone
        branch: Git branch to clone
        token: Personal Access Token for authentication

    Returns:
        str: Path to cloned repository or None if failed
    """
    try:
        # Extract repo name if folder not specified
        if not folder_name:
            folder_name = Path(repo_url).stem.replace('.git', '')

        clone_path = f"{workspace_dir}/{folder_name}"

        # Build authenticated URL if token provided
        if token:
            if 'github.com' in repo_url:
                auth_url = repo_url.replace('https://', f'https://{token}@')
            elif 'gitlab' in repo_url.lower():
                auth_url = repo_url.replace('https://', f'https://oauth2:{token}@')
            else:
                auth_url = repo_url
        else:
            auth_url = repo_url

        # Check if directory already exists
        result = conn.run(f"test -d {clone_path}", warn=True)
        if result.ok:
            console.print(f"  ⚠ Directory {clone_path} already exists")
            # Pull latest changes
            conn.run(f"cd {clone_path} && git pull origin {branch}", hide=True)
            console.print(f"  ✓ Pulled latest changes from {branch}")
        else:
            # Clone the repository
            result = conn.run(
                f"cd {workspace_dir} && git clone -b {branch} {auth_url} {folder_name}",
                hide=True,
                warn=True
            )

            if result.ok:
                console.print(f"  ✓ Repository cloned to {clone_path}")
            else:
                console.print(f"  ✗ Failed to clone repository: {result.stderr}")
                return None

        return clone_path

    except Exception as e:
        console.print(f"  ✗ Clone operation failed: {e}")
        return None


def setup_git_config(conn: Connection, name: Optional[str] = None, email: Optional[str] = None) -> bool:
    """
    Configure git user settings

    Args:
        conn: Fabric SSH connection
        name: Git user name
        email: Git user email

    Returns:
        bool: True if successful
    """
    try:
        if name:
            conn.run(f'git config --global user.name "{name}"', hide=True)
            console.print(f"  ✓ Set git user.name: {name}")

        if email:
            conn.run(f'git config --global user.email "{email}"', hide=True)
            console.print(f"  ✓ Set git user.email: {email}")

        return True

    except Exception as e:
        console.print(f"  ✗ Git config failed: {e}")
        return False