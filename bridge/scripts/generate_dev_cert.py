"""Generate a self-signed certificate for local HTTPS.

    python scripts/generate_dev_cert.py --out certs --host localhost --host 127.0.0.1

Self-signed certificates are for development only; clients must either trust the
certificate or pass --insecure/verify=False. Use a real certificate (or a
TLS-terminating proxy) for anything reachable beyond localhost.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="certs", help="Output directory (default: certs)")
    parser.add_argument(
        "--host",
        action="append",
        default=None,
        help="Hostname or IP for the SAN list. Repeatable. Default: localhost, 127.0.0.1",
    )
    parser.add_argument("--days", type=int, default=365, help="Validity in days (default: 365)")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("This script needs the 'cryptography' package: pip install cryptography")
        return 2

    hosts = args.host or ["localhost", "127.0.0.1"]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / "cert.pem"
    key_path = out_dir / "key.pem"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, hosts[0]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MT5 Bridge (dev)"),
        ]
    )

    sans: list[x509.GeneralName] = []
    for host in hosts:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            sans.append(x509.DNSName(host))

    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=args.days))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.chmod(0o600)

    print(f"Wrote {cert_path} and {key_path} (SAN: {', '.join(hosts)})")
    print("Add to your .env:")
    print(f"  SSL_CERTFILE={cert_path}")
    print(f"  SSL_KEYFILE={key_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
