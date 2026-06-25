"""
Comprehensive file type definitions for Streamlit v2 file upload

This module contains all supported file extensions organized by category.
"""

# Document & Word Processing formats
DOCUMENT_FORMATS = [
    'pdf', 'doc', 'docx', 'odt', 'rtf', 'tex', 'wpd', 'txt', 'md', 'rst', 'adoc', 'org'
]

# Markup Languages
MARKUP_FORMATS = [
    'html', 'htm', 'xhtml', 'xml', 'xsl', 'xslt', 'svg', 'mathml', 'rss', 'atom', 'rdf',
    'xaml', 'yaml', 'yml', 'toml', 'ini', 'conf', 'cfg', 'properties'
]

# Data & Structured formats
DATA_FORMATS = [
    'json', 'jsonl', 'json5', 'ndjson', 'geojson', 'bson', 'cbor', 'msgpack',
    'csv', 'tsv', 'psv', 'dsv'
]

# Spreadsheet formats
SPREADSHEET_FORMATS = [
    'xls', 'xlsx', 'xlsm', 'xlsb', 'xltx', 'xltm', 'ods', 'fods', 'dif', 'prn'
]

# Programming Languages - Systems & Low-level
PROG_SYSTEMS = [
    'c', 'h', 'cpp', 'cc', 'cxx', 'hpp', 'hxx', 'c++', 'asm', 's', 'S'
]

# Programming Languages - JVM
PROG_JVM = [
    'java', 'kt', 'kts', 'scala', 'sc', 'clj', 'cljs', 'cljc', 'edn', 'groovy', 'gvy'
]

# Programming Languages - .NET
PROG_DOTNET = [
    'cs', 'vb', 'fs', 'fsi', 'fsx', 'fsscript'
]

# Programming Languages - Web
PROG_WEB = [
    'js', 'mjs', 'cjs', 'jsx', 'ts', 'tsx', 'd.ts', 'coffee', 'ls', 'dart',
    'php', 'php3', 'php4', 'php5', 'php7', 'phtml'
]

# Programming Languages - Scripting
PROG_SCRIPTING = [
    'py', 'pyw', 'pyx', 'pxd', 'pxi', 'pyc', 'pyo', 'pyd',
    'rb', 'rbw', 'rake', 'gemspec',
    'pl', 'pm', 'pod', 't', 'cgi',
    'lua', 'moon', 'tcl', 'tk',
    'sh', 'bash', 'zsh', 'fish', 'ksh', 'csh', 'ps1', 'psm1', 'psd1', 'bat', 'cmd'
]

# Programming Languages - Functional
PROG_FUNCTIONAL = [
    'hs', 'lhs', 'elm', 'ml', 'mli', 'sml', 'sig', 'fun', 'fsharp',
    'erl', 'hrl', 'ex', 'exs', 'eex', 'leex',
    'lisp', 'lsp', 'cl', 'el', 'elc', 'scm', 'ss', 'rkt'
]

# Programming Languages - Modern
PROG_MODERN = [
    'go', 'rs', 'swift', 'kt', 'kts', 'nim', 'nims', 'nimble',
    'jl', 'zig', 'v', 'vsh', 'vlang'
]

# Database & Query languages
DATABASE_FORMATS = [
    'sql', 'mysql', 'pgsql', 'sqlite', 'ora', 'ddl', 'dml',
    'graphql', 'gql', 'sparql', 'rq', 'cypher', 'cql'
]

# Mobile development
MOBILE_FORMATS = [
    'swift', 'm', 'mm', 'h', 'plist', 'storyboard', 'xib',
    'java', 'kt', 'gradle', 'aar', 'apk'
]

# Other programming languages
PROG_OTHER = [
    'r', 'R', 'Rmd', 'Rnw', 'mat', 'm', 'wl', 'nb', 'cdf',
    'pas', 'pp', 'inc', 'lpr', 'dpr',
    'f', 'for', 'f90', 'f95', 'f03', 'f08',
    'cob', 'cbl', 'cpy', 'ada', 'adb', 'ads',
    'awk', 'sed', 'vim', 'vimrc', 'emacs'
]

# Schema formats
SCHEMA_FORMATS = [
    'xsd', 'dtd', 'rng', 'rnc', 'avsc', 'proto', 'thrift', 'fbs'
]

# Bioinformatics formats
BIOINFORMATICS_FORMATS = [
    # Sequence formats
    'fasta', 'fa', 'fna', 'ffn', 'faa', 'frn',
    'fastq', 'fq', 'sam', 'bam', 'cram',
    # Variant and annotation formats
    'vcf', 'bcf', 'gff', 'gff3', 'gtf', 'bed', 'bedgraph', 'wig', 'bigwig', 'bw',
    # Structure formats
    'pdb', 'cif', 'mmcif', 'mol', 'mol2', 'sdf', 'xyz', 'pdbqt',
    # Database formats
    'gbk', 'gb', 'genbank', 'embl', 'swiss', 'gpff'
]

# Scientific & Physics formats
SCIENTIFIC_FORMATS = [
    'hdf', 'hdf4', 'hdf5', 'h5', 'he5', 'nc', 'nc4', 'netcdf',
    'fits', 'fit', 'fts', 'mat', 'fig', 'mdl', 'slx',
    'npz', 'npy', 'root', 'rdata', 'rda', 'rds'
]

# Big Data formats
BIGDATA_FORMATS = [
    'parquet', 'pq', 'avro', 'orc', 'feather', 'arrow', 'pickle', 'pkl'
]

# Archive formats
ARCHIVE_FORMATS = [
    'zip', 'tar', 'gz', 'bz2', 'xz', 'lz', 'lzma', 'Z', '7z', 'rar',
    'tgz', 'tbz', 'tbz2', 'txz', 'tar.gz', 'tar.bz2', 'tar.xz',
    'iso', 'dmg', 'pkg', 'deb', 'rpm', 'msi', 'exe'
]

# Container & DevOps formats
DEVOPS_FORMATS = [
    'dockerfile', 'containerfile', 'docker-compose.yml', 'docker-compose.yaml',
    'jenkinsfile', 'vagrantfile', 'makefile', 'cmake', 'rakefile',
    'gemfile', 'pipfile', 'requirements.txt', 'package.json', 'pom.xml', 'build.gradle'
]

# Log & Output formats
LOG_FORMATS = [
    'log', 'out', 'err', 'stdout', 'stderr', 'trace'
]

# Combine all programming language formats
ALL_PROGRAMMING_FORMATS = (
    PROG_SYSTEMS + PROG_JVM + PROG_DOTNET + PROG_WEB +
    PROG_SCRIPTING + PROG_FUNCTIONAL + PROG_MODERN +
    PROG_OTHER + MOBILE_FORMATS
)

# Main list of all supported file types
SUPPORTED_FILE_TYPES = sorted(list(set(
    DOCUMENT_FORMATS +
    MARKUP_FORMATS +
    DATA_FORMATS +
    SPREADSHEET_FORMATS +
    ALL_PROGRAMMING_FORMATS +
    DATABASE_FORMATS +
    SCHEMA_FORMATS +
    BIOINFORMATICS_FORMATS +
    SCIENTIFIC_FORMATS +
    BIGDATA_FORMATS +
    ARCHIVE_FORMATS +
    DEVOPS_FORMATS +
    LOG_FORMATS
)))

# Helper function to get file types by category
def get_file_types_by_category(category: str) -> list:
    """
    Get file types for a specific category.

    Args:
        category: Category name (e.g., 'document', 'programming', 'data', etc.)

    Returns:
        List of file extensions for the category
    """
    categories = {
        'document': DOCUMENT_FORMATS,
        'markup': MARKUP_FORMATS,
        'data': DATA_FORMATS,
        'spreadsheet': SPREADSHEET_FORMATS,
        'programming': ALL_PROGRAMMING_FORMATS,
        'database': DATABASE_FORMATS,
        'schema': SCHEMA_FORMATS,
        'bioinformatics': BIOINFORMATICS_FORMATS,
        'scientific': SCIENTIFIC_FORMATS,
        'bigdata': BIGDATA_FORMATS,
        'archive': ARCHIVE_FORMATS,
        'devops': DEVOPS_FORMATS,
        'log': LOG_FORMATS
    }
    return categories.get(category.lower(), [])

# Helper function to check if a file type is supported
def is_supported_file_type(extension: str) -> bool:
    """
    Check if a file extension is supported.

    Args:
        extension: File extension (with or without dot)

    Returns:
        True if supported, False otherwise
    """
    # Remove leading dot if present
    ext = extension.lstrip('.')
    return ext.lower() in SUPPORTED_FILE_TYPES

# Helper function to get category for a file type
def get_file_category(extension: str) -> str:
    """
    Get the category for a file extension.

    Args:
        extension: File extension (with or without dot)

    Returns:
        Category name or 'unknown' if not found
    """
    ext = extension.lstrip('.').lower()

    category_map = {
        'document': DOCUMENT_FORMATS,
        'markup': MARKUP_FORMATS,
        'data': DATA_FORMATS,
        'spreadsheet': SPREADSHEET_FORMATS,
        'programming': ALL_PROGRAMMING_FORMATS,
        'database': DATABASE_FORMATS,
        'schema': SCHEMA_FORMATS,
        'bioinformatics': BIOINFORMATICS_FORMATS,
        'scientific': SCIENTIFIC_FORMATS,
        'bigdata': BIGDATA_FORMATS,
        'archive': ARCHIVE_FORMATS,
        'devops': DEVOPS_FORMATS,
        'log': LOG_FORMATS
    }

    for category, extensions in category_map.items():
        if ext in extensions:
            return category

    return 'unknown'

# Export statistics
def get_file_type_statistics() -> dict:
    """
    Get statistics about supported file types.

    Returns:
        Dictionary with category counts and total
    """
    return {
        'document': len(DOCUMENT_FORMATS),
        'markup': len(MARKUP_FORMATS),
        'data': len(DATA_FORMATS),
        'spreadsheet': len(SPREADSHEET_FORMATS),
        'programming': len(ALL_PROGRAMMING_FORMATS),
        'database': len(DATABASE_FORMATS),
        'schema': len(SCHEMA_FORMATS),
        'bioinformatics': len(BIOINFORMATICS_FORMATS),
        'scientific': len(SCIENTIFIC_FORMATS),
        'bigdata': len(BIGDATA_FORMATS),
        'archive': len(ARCHIVE_FORMATS),
        'devops': len(DEVOPS_FORMATS),
        'log': len(LOG_FORMATS),
        'total': len(SUPPORTED_FILE_TYPES)
    }