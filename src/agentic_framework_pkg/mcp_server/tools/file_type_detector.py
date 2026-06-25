"""
File Type Detection Module

Provides content-based file type detection when filename/extension is not available.
Uses file signatures (magic numbers), MIME type detection, and content analysis.
"""

import os
import json
import zipfile
import pandas as pd
from pathlib import Path
from typing import Tuple, Optional
from ...logger_config import get_logger

logger = get_logger(__name__)


class ContentTypeDetector:
    """
    Detect file types using multiple strategies:
    1. File signatures (magic numbers)
    2. ZIP structure analysis (for Office docs)
    3. Content parsing attempts
    4. Text pattern matching
    """

    def __init__(self):
        # File signatures (magic numbers) - first bytes of files
        self.signatures = {
            # Documents
            b'%PDF': '.pdf',
            b'%PDF-': '.pdf',  # Alternative PDF signature

            # Images
            b'\x89PNG\r\n\x1a\n': '.png',
            b'\xFF\xD8\xFF': '.jpg',
            b'GIF89a': '.gif',
            b'GIF87a': '.gif',
            b'BM': '.bmp',
            b'II*\x00': '.tiff',
            b'MM\x00*': '.tiff',
            b'RIFF': '.webp',  # WebP starts with RIFF

            # ZIP-based formats (need further inspection)
            b'PK\x03\x04': None,  # Generic ZIP
            b'PK\x05\x06': None,  # Empty ZIP
            b'PK\x07\x08': None,  # Spanned ZIP

            # Microsoft Office legacy
            b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1': '.xls',  # OLE2 format (old Office)
            b'\x09\x08\x10\x00\x00\x06\x05\x00': '.xls',  # Alternative XLS

            # Archives
            b'Rar!\x1a\x07': '.rar',
            b'\x37\x7A\xBC\xAF\x27\x1C': '.7z',
            b'\x1f\x8b': '.gz',
            b'BZh': '.bz2',

            # Executables/Binary
            b'MZ': '.exe',
            b'\x7fELF': '.elf',
            b'\xCA\xFE\xBA\xBE': '.class',  # Java class
            b'\xFE\xED\xFA': '.dylib',  # Mac library

            # Media
            b'ID3': '.mp3',
            b'\xFF\xFB': '.mp3',  # Alternative MP3
            b'ftyp': '.mp4',  # MP4/M4A (at offset 4)
            b'OggS': '.ogg',
            b'WAVE': '.wav',
            b'fLaC': '.flac',
        }

    async def detect_from_content(self, file_path: str) -> Tuple[str, str]:
        """
        Detect file type from content analysis.

        Args:
            file_path: Path to the file to analyze

        Returns:
            Tuple of (extension, mime_type)
            Returns ('', 'application/octet-stream') if detection fails
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found for type detection: {file_path}")
            return '', 'application/octet-stream'

        try:
            # Method 1: Check file signatures
            extension, mime_type = self._check_signatures(file_path)
            if extension:
                logger.info(f"Detected {extension} from file signature")
                return extension, mime_type

            # Method 2: Check if it's a ZIP-based format
            if self._is_zip_file(file_path):
                extension, mime_type = self._detect_zip_based(file_path)
                if extension:
                    logger.info(f"Detected {extension} from ZIP structure")
                    return extension, mime_type

            # Method 3: Try to parse as structured data
            extension, mime_type = self._detect_structured_data(file_path)
            if extension:
                logger.info(f"Detected {extension} from structured data parsing")
                return extension, mime_type

            # Method 4: Try to read as text and detect patterns
            extension, mime_type = self._detect_text_format(file_path)
            if extension:
                logger.info(f"Detected {extension} from text patterns")
                return extension, mime_type

            logger.warning(f"Could not detect file type for: {file_path}")
            return '', 'application/octet-stream'

        except Exception as e:
            logger.error(f"Error during file type detection: {e}", exc_info=True)
            return '', 'application/octet-stream'

    def _check_signatures(self, file_path: str) -> Tuple[str, str]:
        """Check file signatures (magic numbers)"""
        try:
            with open(file_path, 'rb') as f:
                # Read first 16 bytes for signature detection
                header = f.read(16)

                # Check for MP4 (ftyp at offset 4)
                if len(header) > 8 and header[4:8] == b'ftyp':
                    return '.mp4', 'video/mp4'

                # Check all signatures
                for signature, ext in self.signatures.items():
                    if header.startswith(signature):
                        if ext:
                            mime_type = self._extension_to_mime(ext)
                            return ext, mime_type
                        break

            return '', ''
        except Exception as e:
            logger.error(f"Error checking file signatures: {e}")
            return '', ''

    def _is_zip_file(self, file_path: str) -> bool:
        """Check if file is a valid ZIP archive"""
        try:
            with zipfile.ZipFile(file_path, 'r'):
                return True
        except (zipfile.BadZipFile, Exception):
            return False

    def _detect_zip_based(self, file_path: str) -> Tuple[str, str]:
        """Detect Office document types from ZIP structure"""
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()

                # Check for Office Open XML formats
                if any('word/' in n for n in names):
                    if any('document.xml' in n for n in names):
                        return '.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

                elif any('xl/' in n for n in names):
                    if any('workbook.xml' in n for n in names):
                        return '.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

                elif any('ppt/' in n for n in names):
                    if any('presentation.xml' in n for n in names):
                        return '.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

                # Check for OpenDocument formats
                elif 'content.xml' in names and 'META-INF/manifest.xml' in names:
                    # Read manifest to determine type
                    try:
                        manifest = zf.read('META-INF/manifest.xml').decode('utf-8')
                        if 'application/vnd.oasis.opendocument.text' in manifest:
                            return '.odt', 'application/vnd.oasis.opendocument.text'
                        elif 'application/vnd.oasis.opendocument.spreadsheet' in manifest:
                            return '.ods', 'application/vnd.oasis.opendocument.spreadsheet'
                        elif 'application/vnd.oasis.opendocument.presentation' in manifest:
                            return '.odp', 'application/vnd.oasis.opendocument.presentation'
                    except:
                        pass

                # Check for EPUB
                elif 'META-INF/container.xml' in names:
                    return '.epub', 'application/epub+zip'

                # Check for JAR
                elif 'META-INF/MANIFEST.MF' in names:
                    return '.jar', 'application/java-archive'

                # Generic ZIP
                return '.zip', 'application/zip'

        except Exception as e:
            logger.error(f"Error detecting ZIP-based format: {e}")
            return '', ''

    def _detect_structured_data(self, file_path: str) -> Tuple[str, str]:
        """Try to detect structured data formats (CSV, JSON, etc.)"""
        # Try CSV detection
        try:
            df = pd.read_csv(file_path, nrows=5)
            if len(df.columns) > 1 and len(df) > 0:
                # Looks like valid CSV
                logger.info(f"Successfully parsed as CSV with {len(df.columns)} columns")
                return '.csv', 'text/csv'
        except Exception:
            pass

        # Try JSON detection
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(10000)  # Read first 10KB

                # Try to parse as JSON
                if content.strip().startswith('{') or content.strip().startswith('['):
                    json.loads(content)
                    return '.json', 'application/json'
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        # Try Excel detection (if pandas can read it)
        try:
            df = pd.read_excel(file_path, nrows=5)
            if len(df.columns) > 0:
                return '.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        except Exception:
            pass

        return '', ''

    def _detect_text_format(self, file_path: str) -> Tuple[str, str]:
        """Detect text-based formats by content patterns"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read first 5000 characters
                content = f.read(5000)
                lines = content.split('\n')[:50]  # First 50 lines

                # HTML detection
                if '<!DOCTYPE html' in content.lower() or '<html' in content.lower()[:500]:
                    return '.html', 'text/html'

                # XML detection
                if content.strip().startswith('<?xml'):
                    return '.xml', 'application/xml'

                # Markdown detection
                md_indicators = [
                    any(line.startswith('#') for line in lines[:10]),  # Headers
                    '```' in content,  # Code blocks
                    any(line.strip().startswith('- ') or line.strip().startswith('* ') for line in lines),  # Lists
                    any(line.strip().startswith('1. ') or line.strip().startswith('2. ') for line in lines),  # Numbered lists
                    '[' in content and '](' in content,  # Links
                ]
                if sum(md_indicators) >= 2:
                    return '.md', 'text/markdown'

                # LaTeX detection
                if '\\documentclass' in content or '\\begin{document}' in content:
                    return '.tex', 'application/x-latex'

                # SQL detection
                sql_keywords = ['CREATE TABLE', 'SELECT', 'INSERT INTO', 'UPDATE', 'DELETE FROM', 'ALTER TABLE']
                if any(keyword in content.upper() for keyword in sql_keywords):
                    return '.sql', 'application/sql'

                # Python detection
                if 'import ' in content or 'from ' in content or 'def ' in content or 'class ' in content:
                    if content.count('def ') > 0 or content.count('class ') > 0:
                        return '.py', 'text/x-python'

                # YAML detection
                if any(line.strip().endswith(':') for line in lines[:10]) and '  ' in content:
                    return '.yaml', 'application/x-yaml'

                # INI/Config detection
                if any('[' in line and ']' in line for line in lines[:10]):
                    return '.ini', 'text/plain'

                # Generic text file
                if len(content.strip()) > 0:
                    return '.txt', 'text/plain'

        except UnicodeDecodeError:
            # Not a text file
            pass
        except Exception as e:
            logger.error(f"Error detecting text format: {e}")

        return '', ''

    def _extension_to_mime(self, extension: str) -> str:
        """Map file extension to MIME type"""
        mime_map = {
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.webp': 'image/webp',
            '.csv': 'text/csv',
            '.txt': 'text/plain',
            '.html': 'text/html',
            '.xml': 'application/xml',
            '.json': 'application/json',
            '.md': 'text/markdown',
            '.tex': 'application/x-latex',
            '.py': 'text/x-python',
            '.sql': 'application/sql',
            '.yaml': 'application/x-yaml',
            '.yml': 'application/x-yaml',
            '.ini': 'text/plain',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.zip': 'application/zip',
            '.rar': 'application/x-rar-compressed',
            '.7z': 'application/x-7z-compressed',
            '.gz': 'application/gzip',
            '.tar': 'application/x-tar',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.wav': 'audio/wav',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac',
        }
        return mime_map.get(extension, 'application/octet-stream')