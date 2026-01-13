"""
Consolidated delete operations for pylovo.
"""
import argparse
from pylovo.grid_generator import GridGenerator


def delete_networks(plz: int, version_id: str):
    """Delete networks for a specific PLZ and version."""
    gg = GridGenerator(plz=plz)
    gg.dbc.delete_plz_from_all_tables(plz, version_id)
    print(f"✓ Deleted networks for PLZ {plz}, version {version_id}")


def delete_version(version_id: str):
    """Delete all networks for a version across all PLZ."""
    gg = GridGenerator(plz="91301")  # dummy plz for initialization
    gg.dbc.delete_version_from_all_tables(version_id=version_id)
    print(f"✓ Deleted all networks for version {version_id}")


def delete_transformers(plz: str):
    """Delete transformers for a specific PLZ."""
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    dbc_client.delete_transformers()
    print(f"✓ Deleted transformers for PLZ {plz}")


def delete_classification_version(classification_version: str):
    """Delete classification version data."""
    gg = GridGenerator()  # initialization without specific plz
    gg.dbc.delete_classification_version_from_related_tables(classification_version)
    print(f"✓ Deleted classification version {classification_version}")


def main():
    """Main entry point with subcommands for different delete operations."""
    parser = argparse.ArgumentParser(
        prog="pylovo-delete",
        description="Delete various pylovo data from database"
    )

    subparsers = parser.add_subparsers(dest="command", help="Delete operation to perform")

    # Subcommand: networks
    networks_parser = subparsers.add_parser(
        "networks",
        help="Delete networks for a specific PLZ and version"
    )
    networks_parser.add_argument("--plz", type=int, required=True, help="Postal code")
    networks_parser.add_argument("--version", type=str, required=True, help="Version ID")

    # Subcommand: version
    version_parser = subparsers.add_parser(
        "version",
        help="Delete all networks for a version across all PLZ"
    )
    version_parser.add_argument("--version", type=str, required=True, help="Version ID")

    # Subcommand: transformers
    trafos_parser = subparsers.add_parser(
        "transformers",
        help="Delete transformers for a PLZ"
    )
    trafos_parser.add_argument("--plz", type=str, required=True, help="Postal code")

    # Subcommand: classification
    class_parser = subparsers.add_parser(
        "classification",
        help="Delete classification version data"
    )
    class_parser.add_argument("--version", type=str, required=True, help="Classification version")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "networks":
            delete_networks(args.plz, args.version)
        elif args.command == "version":
            delete_version(args.version)
        elif args.command == "transformers":
            delete_transformers(args.plz)
        elif args.command == "classification":
            delete_classification_version(args.version)
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

