"""
Main orchestration script for ADEPT deployment bootstrap.

Usage:
    # Full two-VM setup
    python bootstrap_main.py deploy \
        --hostname vm1.api.agentic.local \
        --peer-hostname vm2.api.agentic.local \
        --vm1-ip 192.168.1.100 \
        --vm2-ip 192.168.1.101 \
        --email admin@example.com

    # Certificate-only
    python bootstrap_main.py letsencrypt \
        --hostname vm1.api.agentic.local \
        --email admin@example.com

    # A2A registration-only
    python bootstrap_main.py a2a-register \
        --alias vm2-gateway \
        --url https://vm2.api.agentic.local
"""

import asyncio
import click
import logging
import sys
from pathlib import Path

# Add modules directory to path
sys.path.insert(0, str(Path(__file__).parent / "modules"))

from modules.letsencrypt_manager import LetsEncryptManager
from modules.a2a_registrar import A2ARegistrar
from modules.artifact_generator import ArtifactGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """ADEPT Deployment Bootstrap Tool"""
    pass


@cli.command()
@click.option("--hostname", required=True, help="This VM's hostname")
@click.option("--peer-hostname", required=True, help="Peer VM's hostname")
@click.option("--vm1-ip", required=True, help="VM1 IP address")
@click.option("--vm2-ip", required=True, help="VM2 IP address")
@click.option("--email", required=True, help="Email for Let's Encrypt")
@click.option("--challenge", default="dns", type=click.Choice(["dns", "http"]))
@click.option("--output-dir", default="/output", help="Artifact output directory")
def deploy(hostname: str, peer_hostname: str, vm1_ip: str, vm2_ip: str,
          email: str, challenge: str, output_dir: str):
    """Generate complete deployment artifacts for two-VM setup"""

    logger.info(f"🚀 Generating ADEPT two-VM deployment artifacts")
    logger.info(f"Local: {hostname}")
    logger.info(f"Peer: {peer_hostname}")
    logger.info(f"Output: {output_dir}")

    artifact_gen = ArtifactGenerator(output_dir)

    # Phase 1: Generate Let's Encrypt certificate (if certbot available)
    logger.info("Phase 1: Let's Encrypt certificate setup...")
    le_manager = LetsEncryptManager(hostname, email, challenge_type=challenge)

    # Check if certificates already exist
    le_live = Path(f"/etc/letsencrypt/live/{hostname}")
    if le_live.exists():
        logger.info(f"Found existing certificates at {le_live}")
        if not le_manager.copy_to_output(f"{output_dir}/certs"):
            logger.warning("Failed to export existing certificates")
    else:
        logger.info("No existing certificates found - generate with certbot manually or run letsencrypt command")
        logger.info(f"  certbot certonly --manual --preferred-challenges {challenge} -d {hostname} --email {email}")

    # Generate renewal hook regardless
    le_manager.generate_renewal_hook(f"{output_dir}/certs")

    # Phase 2: Generate configuration artifacts
    logger.info("Phase 2: Generating configuration artifacts...")

    vm1_hostname = hostname if "vm1" in hostname else peer_hostname
    vm2_hostname = peer_hostname if "vm2" in peer_hostname else hostname

    artifact_gen.generate_env_updates(hostname)
    artifact_gen.generate_hosts_entries(vm1_hostname, vm1_ip, vm2_hostname, vm2_ip)
    artifact_gen.generate_cert_apply_script(hostname)
    artifact_gen.generate_restart_script()

    # Phase 3: Generate A2A registration artifacts
    logger.info("Phase 3: Generating A2A registration artifacts...")

    peer_alias = f"{peer_hostname.split('.')[0]}-gateway"
    artifact_gen.generate_a2a_registration_payload(
        alias=peer_alias,
        public_url=f"https://{peer_hostname}",
        description=f"Peer Gateway at {peer_hostname}",
        tags=["production", peer_hostname.split('.')[0]]
    )
    artifact_gen.generate_a2a_registration_script(
        alias=peer_alias,
        public_url=f"https://{peer_hostname}",
        description=f"Peer Gateway at {peer_hostname}",
        tags=["production", peer_hostname.split('.')[0]]
    )

    # Phase 4: Generate deployment guide
    logger.info("Phase 4: Generating deployment guide...")
    artifact_gen.generate_deployment_guide(vm1_hostname, vm2_hostname)

    # Summary
    logger.info("")
    logger.info("✅ Artifact generation complete!")
    logger.info("")
    logger.info("Generated artifacts:")
    logger.info(f"  📁 Certificates: {output_dir}/certs/")
    logger.info(f"  📁 Configurations: {output_dir}/configs/")
    logger.info(f"  📁 Scripts: {output_dir}/scripts/")
    logger.info(f"  📁 A2A Registration: {output_dir}/a2a/")
    logger.info(f"  📄 Deployment Guide: {output_dir}/DEPLOYMENT_GUIDE.md")
    logger.info("")
    logger.info("Next steps:")
    logger.info(f"  1. Review artifacts in {output_dir}/")
    logger.info("  2. Copy artifact directory to both VMs")
    logger.info("  3. Follow DEPLOYMENT_GUIDE.md on each VM")


@cli.command()
@click.option("--hostname", required=True)
@click.option("--email", required=True)
@click.option("--challenge", default="dns", type=click.Choice(["dns", "http"]))
@click.option("--output-dir", default="/output", help="Output directory for certificates")
def letsencrypt(hostname: str, email: str, challenge: str, output_dir: str):
    """Generate Let's Encrypt certificate and export to output"""

    logger.info(f"🔐 Generating Let's Encrypt certificate for {hostname}")

    le_manager = LetsEncryptManager(hostname, email, challenge_type=challenge)

    if not le_manager.generate_certificate():
        logger.error("Certificate generation failed")
        return

    if not le_manager.copy_to_output(f"{output_dir}/certs"):
        logger.error("Failed to export certificates")
        return

    le_manager.generate_renewal_hook(f"{output_dir}/certs")

    logger.info("✅ Certificate generation complete")
    logger.info(f"Certificates exported to: {output_dir}/certs/")


@cli.command("a2a-register")
@click.option("--alias", required=True, help="Peer gateway alias")
@click.option("--url", required=True, help="Peer gateway URL")
@click.option("--description", default="", help="Description")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--registry-url",
              default=None,
              envvar="GATEWAY_REGISTRY_URL",
              help="Gateway registry URL (default: https://${PUBLIC_HOSTNAME}/internal/registry)")
def a2a_register(alias: str, url: str, description: str, tags: str, registry_url: str):
    """Register peer gateway in A2A mesh (Phase 1 operation)

    Requires /etc/hosts entry: 127.0.0.1 api.agentic.local (for local testing)
    Or set PUBLIC_HOSTNAME environment variable for production.
    """

    logger.info(f"📝 Registering peer gateway: {alias}")
    logger.info(f"Public URL: {url}")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    registrar = A2ARegistrar(registry_url=registry_url)  # Uses smart default if None

    logger.info(f"Registry: {registrar.registry_url}")

    success = asyncio.run(registrar.register_peer(
        alias=alias,
        public_url=url,
        description=description,
        tags=tag_list
    ))

    if success:
        logger.info("✅ Registration successful")
    else:
        logger.error("❌ Registration failed")
        sys.exit(1)


@cli.command("a2a-list")
@click.option("--registry-url",
              default=None,
              envvar="GATEWAY_REGISTRY_URL",
              help="Gateway registry URL (default: https://${PUBLIC_HOSTNAME}/internal/registry)")
def a2a_list(registry_url: str):
    """List all registered gateway peers (Phase 1/2 operation)

    Requires /etc/hosts entry: 127.0.0.1 api.agentic.local (for local testing)
    Or set PUBLIC_HOSTNAME environment variable for production.
    """

    registrar = A2ARegistrar(registry_url=registry_url)  # Uses smart default if None

    logger.info(f"📋 Listing registered peers from {registrar.registry_url}")

    peers = asyncio.run(registrar.list_peers())

    if not peers:
        logger.info("No peers registered")
        return

    logger.info(f"Registered peers: {len(peers)}")
    for peer in peers:
        logger.info(f"  - {peer['alias']}: {peer.get('public_url', 'N/A')}")


if __name__ == "__main__":
    cli()
