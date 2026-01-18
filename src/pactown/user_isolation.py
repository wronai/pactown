"""
User isolation module for pactown.

Provides Linux user-based sandbox isolation for multi-tenant SaaS:
- Create isolated Linux users per SaaS user
- Run sandboxes under isolated user accounts
- Easy migration of projects between hosts
- Resource limits via cgroups (optional)
"""

import grp
import os
import pwd
import re
import shutil
import subprocess
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from threading import Lock

logger = logging.getLogger("pactown.isolation")


def _sanitize_gecos(value: str) -> str:
    v = str(value or "")
    v = v.replace(":", "_")
    v = re.sub(r"[\x00\r\n\t]", " ", v)
    v = re.sub(r"\s+", " ", v).strip()
    if not v:
        v = "pactown-user"
    return v[:200]


@dataclass
class IsolatedUser:
    """Represents an isolated Linux user for sandbox execution."""
    saas_user_id: str
    linux_username: str
    linux_uid: int
    linux_gid: int
    home_dir: Path
    created_at: float = field(default_factory=lambda: __import__('time').time())
    
    def to_dict(self) -> dict:
        return {
            "saas_user_id": self.saas_user_id,
            "linux_username": self.linux_username,
            "linux_uid": self.linux_uid,
            "linux_gid": self.linux_gid,
            "home_dir": str(self.home_dir),
            "created_at": self.created_at,
        }


class UserIsolationManager:
    """
    Manages isolated Linux users for sandbox execution.
    
    Each SaaS user gets a dedicated Linux user account:
    - Username: pactown_<hash(saas_user_id)>
    - Home dir: /home/pactown_users/<username>
    - All sandboxes run under this user
    
    Benefits:
    - Process isolation (different UIDs)
    - File system isolation (home directories)
    - Easy migration (tar user's home dir)
    - Resource limits via cgroups
    """
    
    PREFIX = "pactown_"
    BASE_UID = 60000  # Start UIDs from 60000
    BASE_GID = 60000
    
    def __init__(
        self,
        users_base: Path = Path("/home/pactown_users"),
        enable_cgroups: bool = False,
    ):
        self.users_base = users_base
        self.enable_cgroups = enable_cgroups
        self._users: Dict[str, IsolatedUser] = {}
        self._lock = Lock()
        self._next_uid = self.BASE_UID
        
        # Create base directory if running as root
        if os.geteuid() == 0:
            self.users_base.mkdir(parents=True, exist_ok=True)
        
        # Load existing users
        self._load_existing_users()

    def can_isolate(self) -> tuple[bool, str]:
        if os.geteuid() != 0:
            return False, "not running as root"
        if shutil.which("useradd") is None:
            return False, "missing 'useradd' (install 'passwd'/'shadow' tools)"
        if shutil.which("groupadd") is None:
            return False, "missing 'groupadd' (install 'passwd'/'shadow' tools)"
        try:
            self.users_base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"cannot create users_base={self.users_base}: {e}"
        try:
            if not os.access(self.users_base, os.W_OK | os.X_OK):
                return False, f"users_base not writable: {self.users_base}"
        except Exception as e:
            return False, f"cannot check permissions for users_base={self.users_base}: {e}"
        return True, ""
    
    def _load_existing_users(self):
        """Load existing pactown users from system."""
        try:
            for entry in pwd.getpwall():
                if entry.pw_name.startswith(self.PREFIX):
                    # Extract saas_user_id from comment field or username
                    saas_id = entry.pw_gecos or entry.pw_name[len(self.PREFIX):]
                    self._users[saas_id] = IsolatedUser(
                        saas_user_id=saas_id,
                        linux_username=entry.pw_name,
                        linux_uid=entry.pw_uid,
                        linux_gid=entry.pw_gid,
                        home_dir=Path(entry.pw_dir),
                    )
                    if entry.pw_uid >= self._next_uid:
                        self._next_uid = entry.pw_uid + 1
        except Exception as e:
            logger.warning(f"Could not load existing users: {e}")
    
    def _generate_username(self, saas_user_id: str) -> str:
        """Generate Linux username from SaaS user ID."""
        import hashlib
        hash_suffix = hashlib.sha256(saas_user_id.encode()).hexdigest()[:8]
        return f"{self.PREFIX}{hash_suffix}"
    
    def get_or_create_user(self, saas_user_id: str) -> IsolatedUser:
        """Get or create an isolated Linux user for a SaaS user."""
        with self._lock:
            if saas_user_id in self._users:
                return self._users[saas_user_id]
            
            # Create new user
            username = self._generate_username(saas_user_id)
            uid = self._next_uid
            gid = self._next_uid
            home_dir = self.users_base / username

            # If user already exists (deterministic username), reuse it.
            try:
                existing = pwd.getpwnam(username)
                user = IsolatedUser(
                    saas_user_id=saas_user_id,
                    linux_username=existing.pw_name,
                    linux_uid=existing.pw_uid,
                    linux_gid=existing.pw_gid,
                    home_dir=Path(existing.pw_dir),
                )
                self._users[saas_user_id] = user
                if existing.pw_uid >= self._next_uid:
                    self._next_uid = existing.pw_uid + 1
                logger.info(
                    "Reusing existing Linux user %s (uid=%s) for %s",
                    user.linux_username,
                    user.linux_uid,
                    saas_user_id,
                )
                return user
            except KeyError:
                pass
            
            # Check if we can create users (requires root)
            if os.geteuid() != 0:
                # Non-root mode: create virtual user for tracking
                logger.warning(f"Not running as root, creating virtual user for {saas_user_id}")
                user = IsolatedUser(
                    saas_user_id=saas_user_id,
                    linux_username=username,
                    linux_uid=os.getuid(),  # Use current user
                    linux_gid=os.getgid(),
                    home_dir=home_dir,
                )
                self._users[saas_user_id] = user
                
                # Create home directory anyway
                try:
                    home_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    fallback_base = Path(tempfile.gettempdir()) / "pactown_users"
                    fallback_home = fallback_base / username
                    logger.warning(
                        "Could not create users_base home_dir=%s (%s); falling back to %s",
                        home_dir,
                        e,
                        fallback_home,
                    )
                    fallback_home.mkdir(parents=True, exist_ok=True)
                    user.home_dir = fallback_home
                return user

            can_isolate, reason = self.can_isolate()
            if not can_isolate:
                raise RuntimeError(f"User isolation unavailable: {reason}")
            
            try:
                # Create group
                try:
                    grp.getgrnam(username)
                except KeyError:
                    res = subprocess.run(
                        ["groupadd", "-g", str(gid), username],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    if res.stdout:
                        logger.debug("groupadd stdout: %s", res.stdout.strip())
                    if res.stderr:
                        logger.debug("groupadd stderr: %s", res.stderr.strip())
                
                # Create user
                safe_comment = _sanitize_gecos(saas_user_id)
                res = subprocess.run(
                    [
                        "useradd",
                        "-u",
                        str(uid),
                        "-g",
                        str(gid),
                        "-d",
                        str(home_dir),
                        "-m",
                        "-s",
                        "/bin/bash",
                        "-c",
                        safe_comment,
                        username,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if res.stdout:
                    logger.debug("useradd stdout: %s", res.stdout.strip())
                if res.stderr:
                    logger.debug("useradd stderr: %s", res.stderr.strip())
                
                logger.info(f"Created Linux user {username} (uid={uid}) for {saas_user_id}")
                
            except subprocess.CalledProcessError as e:
                stderr = getattr(e, "stderr", None)
                stdout = getattr(e, "stdout", None)
                logger.error(
                    "Failed to create isolated user for %s: cmd=%s returncode=%s stdout=%s stderr=%s",
                    saas_user_id,
                    getattr(e, "cmd", None),
                    getattr(e, "returncode", None),
                    (stdout.strip() if isinstance(stdout, str) else stdout),
                    (stderr.strip() if isinstance(stderr, str) else stderr),
                )
                raise RuntimeError(
                    f"Failed to create isolated user (saas_user_id={saas_user_id}, username={username}): {e}"
                )
            
            user = IsolatedUser(
                saas_user_id=saas_user_id,
                linux_username=username,
                linux_uid=uid,
                linux_gid=gid,
                home_dir=home_dir,
            )
            
            self._users[saas_user_id] = user
            self._next_uid += 1
            
            return user
    
    def get_user(self, saas_user_id: str) -> Optional[IsolatedUser]:
        """Get isolated user without creating."""
        return self._users.get(saas_user_id)
    
    def get_sandbox_path(self, saas_user_id: str, service_id: str) -> Path:
        """Get sandbox path for a specific service under user's home."""
        user = self.get_or_create_user(saas_user_id)
        sandbox_dir = user.home_dir / "sandboxes" / service_id
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        
        # Set ownership if root
        if os.geteuid() == 0:
            os.chown(sandbox_dir, user.linux_uid, user.linux_gid)
        
        return sandbox_dir
    
    def run_as_user(
        self,
        saas_user_id: str,
        command: str,
        cwd: Path,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.Popen:
        """
        Run a command as the isolated user.
        
        Returns subprocess.Popen for the running process.
        """
        user = self.get_or_create_user(saas_user_id)
        
        full_env = os.environ.copy()
        full_env["HOME"] = str(user.home_dir)
        full_env["USER"] = user.linux_username
        full_env["LOGNAME"] = user.linux_username
        if env:
            full_env.update(env)
        
        def set_user():
            """Pre-exec function to switch user."""
            if os.geteuid() == 0:
                os.setgid(user.linux_gid)
                os.setuid(user.linux_uid)
        
        # nosec B602: shell=True required for user commands in isolated sandbox
        # User is isolated via Linux user/group and sandbox directory
        process = subprocess.Popen(
            command,
            shell=True,  # nosec B602
            cwd=str(cwd),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=set_user if os.geteuid() == 0 else None,
        )
        
        logger.info(f"Started process {process.pid} as user {user.linux_username}")
        return process
    
    def list_users(self) -> List[IsolatedUser]:
        """List all isolated users."""
        return list(self._users.values())
    
    def get_user_stats(self, saas_user_id: str) -> Dict[str, Any]:
        """Get stats for a user's sandboxes."""
        user = self.get_user(saas_user_id)
        if not user:
            return {"error": "User not found"}
        
        sandboxes_dir = user.home_dir / "sandboxes"
        if not sandboxes_dir.exists():
            return {
                "user": user.to_dict(),
                "sandbox_count": 0,
                "total_size_mb": 0,
            }
        
        sandbox_count = len(list(sandboxes_dir.iterdir()))
        total_size = sum(
            f.stat().st_size 
            for f in sandboxes_dir.rglob("*") 
            if f.is_file()
        )
        
        return {
            "user": user.to_dict(),
            "sandbox_count": sandbox_count,
            "total_size_mb": total_size / (1024 * 1024),
        }
    
    def export_user_data(self, saas_user_id: str, output_path: Path) -> bool:
        """
        Export user's data for migration.
        
        Creates a tar.gz archive of the user's home directory.
        """
        user = self.get_user(saas_user_id)
        if not user or not user.home_dir.exists():
            return False
        
        try:
            subprocess.run(
                ["tar", "-czf", str(output_path), "-C", str(user.home_dir.parent), user.linux_username],
                check=True,
                capture_output=True,
            )
            logger.info(f"Exported user {saas_user_id} to {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to export user: {e}")
            return False
    
    def import_user_data(self, saas_user_id: str, archive_path: Path) -> bool:
        """
        Import user's data from migration archive.
        """
        user = self.get_or_create_user(saas_user_id)
        
        try:
            # Extract to user's home
            subprocess.run(
                ["tar", "-xzf", str(archive_path), "-C", str(self.users_base)],
                check=True,
                capture_output=True,
            )
            
            # Fix ownership
            if os.geteuid() == 0:
                subprocess.run(
                    ["chown", "-R", f"{user.linux_uid}:{user.linux_gid}", str(user.home_dir)],
                    check=True,
                    capture_output=True,
                )
            
            logger.info(f"Imported user {saas_user_id} from {archive_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to import user: {e}")
            return False
    
    def delete_user(self, saas_user_id: str, delete_home: bool = True) -> bool:
        """Delete an isolated user."""
        user = self.get_user(saas_user_id)
        if not user:
            return False
        
        try:
            if os.geteuid() == 0:
                # Delete Linux user
                cmd = ["userdel"]
                if delete_home:
                    cmd.append("-r")
                cmd.append(user.linux_username)
                subprocess.run(cmd, check=True, capture_output=True)
                subprocess.run(
                    ["groupdel", user.linux_username],
                    capture_output=True,  # May fail if group doesn't exist
                )
            elif delete_home and user.home_dir.exists():
                # Non-root: just delete home directory
                shutil.rmtree(user.home_dir)
            
            del self._users[saas_user_id]
            logger.info(f"Deleted user {saas_user_id}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to delete user: {e}")
            return False


# Global isolation manager instance
_isolation_manager: Optional[UserIsolationManager] = None


def get_isolation_manager() -> UserIsolationManager:
    """Get global isolation manager instance."""
    global _isolation_manager
    if _isolation_manager is None:
        default_base = "/home/pactown_users" if os.geteuid() == 0 else tempfile.gettempdir() + "/pactown_users"
        users_base = Path(os.environ.get("PACTOWN_USERS_BASE", default_base))
        _isolation_manager = UserIsolationManager(users_base=users_base)
    return _isolation_manager
