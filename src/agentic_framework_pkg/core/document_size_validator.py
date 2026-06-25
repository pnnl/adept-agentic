"""
Document Size Validator

Validates document sizes against token budgets and provides recommendations
for optimal processing strategies.
"""

import os
import logging
from typing import Tuple, Optional, Dict, Any
from pathlib import Path
import tiktoken
import PyPDF2
import docx
import zipfile

logger = logging.getLogger(__name__)


class DocumentSizeValidator:
    """Validates document sizes against token budgets."""

    def __init__(self, max_tokens: int = 200_000):
        """
        Initialize the validator.

        Args:
            max_tokens: Maximum token budget (default: 200,000 for Claude)
        """
        self.max_tokens = max_tokens
        self.safety_margin = 0.8  # Use only 80% of budget for safety

        # Initialize tokenizer (using cl100k_base which is close to Claude's tokenizer)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except:
            # Fallback to approximate calculation if tiktoken not available
            self.tokenizer = None
            logger.warning("tiktoken not available, using approximate token counting")

    def estimate_token_count(self, file_path: str) -> int:
        """
        Estimate the token count for a document.

        Args:
            file_path: Path to the document

        Returns:
            Estimated number of tokens
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = file_path.suffix.lower()

        try:
            if file_ext == '.txt':
                return self._estimate_text_file(file_path)
            elif file_ext == '.pdf':
                return self._estimate_pdf_file(file_path)
            elif file_ext in ['.docx', '.doc']:
                return self._estimate_docx_file(file_path)
            elif file_ext == '.md':
                return self._estimate_markdown_file(file_path)
            elif file_ext in ['.csv', '.tsv']:
                return self._estimate_csv_file(file_path)
            elif file_ext == '.json':
                return self._estimate_json_file(file_path)
            elif file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                return self._estimate_image_file(file_path)
            elif file_ext == '.zip':
                return self._estimate_zip_file(file_path)
            else:
                # Default: treat as text
                return self._estimate_text_file(file_path)

        except Exception as e:
            logger.error(f"Error estimating tokens for {file_path}: {e}")
            # Fallback to file size estimation
            return self._estimate_by_size(file_path)

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using tokenizer or approximation."""
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Approximate: 1 token ≈ 4 characters (rough estimate)
            return len(text) // 4

    def _estimate_text_file(self, file_path: Path) -> int:
        """Estimate tokens in a text file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        return self._count_tokens(text)

    def _estimate_pdf_file(self, file_path: Path) -> int:
        """Estimate tokens in a PDF file."""
        total_tokens = 0

        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                num_pages = len(pdf_reader.pages)

                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    total_tokens += self._count_tokens(text)

                # Add overhead for formatting and metadata
                total_tokens = int(total_tokens * 1.1)

        except Exception as e:
            logger.warning(f"Failed to parse PDF, using size estimation: {e}")
            return self._estimate_by_size(file_path)

        return total_tokens

    def _estimate_docx_file(self, file_path: Path) -> int:
        """Estimate tokens in a DOCX file."""
        try:
            doc = docx.Document(file_path)
            text = '\n'.join([paragraph.text for paragraph in doc.paragraphs])

            # Also include table text
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text += '\n' + cell.text

            return self._count_tokens(text)

        except Exception as e:
            logger.warning(f"Failed to parse DOCX, using size estimation: {e}")
            return self._estimate_by_size(file_path)

    def _estimate_markdown_file(self, file_path: Path) -> int:
        """Estimate tokens in a Markdown file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        # Markdown has extra formatting, add 10% overhead
        base_tokens = self._count_tokens(text)
        return int(base_tokens * 1.1)

    def _estimate_csv_file(self, file_path: Path) -> int:
        """Estimate tokens in a CSV file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        # CSV structure adds overhead
        base_tokens = self._count_tokens(text)
        return int(base_tokens * 1.2)

    def _estimate_json_file(self, file_path: Path) -> int:
        """Estimate tokens in a JSON file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        # JSON structure adds significant overhead
        base_tokens = self._count_tokens(text)
        return int(base_tokens * 1.3)

    def _estimate_image_file(self, file_path: Path) -> int:
        """Estimate tokens for an image file."""
        # Images typically generate descriptions of ~500-2000 tokens
        # depending on complexity and OCR content
        file_size_mb = file_path.stat().st_size / (1024 * 1024)

        if file_size_mb < 1:
            return 500  # Small image
        elif file_size_mb < 5:
            return 1000  # Medium image
        else:
            return 2000  # Large/complex image

    def _estimate_zip_file(self, file_path: Path) -> int:
        """Estimate tokens in a ZIP file by summing contained files."""
        total_tokens = 0

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                for file_info in zip_ref.filelist:
                    # Estimate based on uncompressed size
                    # Rough estimate: 4 characters per token
                    estimated_tokens = file_info.file_size // 4
                    total_tokens += estimated_tokens

        except Exception as e:
            logger.warning(f"Failed to analyze ZIP, using size estimation: {e}")
            return self._estimate_by_size(file_path)

        return total_tokens

    def _estimate_by_size(self, file_path: Path) -> int:
        """Fallback: estimate tokens by file size."""
        file_size = file_path.stat().st_size

        # Rough estimates based on file size
        # Assuming ~4 bytes per token on average
        return file_size // 4

    def can_process_document(
        self,
        file_path: str,
        budget: Optional[int] = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Check if a document can be processed within the token budget.

        Args:
            file_path: Path to the document
            budget: Optional custom token budget (uses default if not specified)

        Returns:
            Tuple of:
            - can_process: Whether the document can be processed
            - error_message: Error message if cannot process
            - info: Dictionary with detailed information
        """
        budget = budget or self.max_tokens
        effective_budget = int(budget * self.safety_margin)

        try:
            estimated_tokens = self.estimate_token_count(file_path)

            info = {
                "file_path": file_path,
                "estimated_tokens": estimated_tokens,
                "token_budget": budget,
                "effective_budget": effective_budget,
                "safety_margin": self.safety_margin,
                "file_size_bytes": os.path.getsize(file_path)
            }

            if estimated_tokens <= effective_budget:
                info["recommendation"] = "Document can be processed normally"
                return True, None, info

            # Calculate recommendations for oversized documents
            chunks_needed = (estimated_tokens // effective_budget) + 1
            recommended_chunk_size = estimated_tokens // chunks_needed

            info["chunks_needed"] = chunks_needed
            info["recommended_chunk_size"] = recommended_chunk_size

            error_msg = (
                f"Document too large: {estimated_tokens:,} tokens "
                f"(budget: {effective_budget:,} tokens). "
                f"Consider splitting into {chunks_needed} parts or "
                f"using chunk size of {recommended_chunk_size} tokens."
            )

            return False, error_msg, info

        except Exception as e:
            error_msg = f"Failed to validate document: {e}"
            return False, error_msg, {"error": str(e)}

    def get_processing_strategy(
        self,
        file_path: str,
        budget: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get recommended processing strategy for a document.

        Args:
            file_path: Path to the document
            budget: Optional custom token budget

        Returns:
            Dictionary with processing strategy recommendations
        """
        can_process, error_msg, info = self.can_process_document(file_path, budget)

        strategy = {
            "file_path": file_path,
            "can_process_full": can_process,
            "estimated_tokens": info.get("estimated_tokens", 0),
            "file_size_mb": info.get("file_size_bytes", 0) / (1024 * 1024)
        }

        if can_process:
            strategy["strategy"] = "full_document"
            strategy["chunk_size"] = 1000  # Default chunk size
            strategy["chunk_overlap"] = 200
        else:
            # Need chunking strategy
            tokens = info.get("estimated_tokens", 0)
            effective_budget = info.get("effective_budget", self.max_tokens * 0.8)

            if tokens < effective_budget * 2:
                # Can handle with moderate chunking
                strategy["strategy"] = "moderate_chunking"
                strategy["chunk_size"] = 512
                strategy["chunk_overlap"] = 100
            elif tokens < effective_budget * 5:
                # Need aggressive chunking
                strategy["strategy"] = "aggressive_chunking"
                strategy["chunk_size"] = 256
                strategy["chunk_overlap"] = 50
            else:
                # Need to split document
                strategy["strategy"] = "split_document"
                strategy["split_parts"] = info.get("chunks_needed", 10)
                strategy["chunk_size"] = 256
                strategy["chunk_overlap"] = 25

            strategy["warning"] = error_msg

        return strategy

    def validate_batch(
        self,
        file_paths: list[str],
        budget: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Validate a batch of documents.

        Args:
            file_paths: List of file paths to validate
            budget: Optional custom token budget

        Returns:
            Dictionary with batch validation results
        """
        budget = budget or self.max_tokens
        results = {
            "total_files": len(file_paths),
            "can_process": [],
            "cannot_process": [],
            "total_estimated_tokens": 0,
            "recommendations": []
        }

        for file_path in file_paths:
            can_process, error_msg, info = self.can_process_document(file_path, budget)

            file_info = {
                "file": file_path,
                "tokens": info.get("estimated_tokens", 0),
                "size_mb": info.get("file_size_bytes", 0) / (1024 * 1024)
            }

            if can_process:
                results["can_process"].append(file_info)
            else:
                file_info["error"] = error_msg
                results["cannot_process"].append(file_info)

            results["total_estimated_tokens"] += info.get("estimated_tokens", 0)

        # Overall recommendations
        if results["total_estimated_tokens"] > budget:
            results["recommendations"].append(
                f"Process files in batches. Total tokens ({results['total_estimated_tokens']:,}) "
                f"exceeds budget ({budget:,})"
            )

        if results["cannot_process"]:
            results["recommendations"].append(
                f"{len(results['cannot_process'])} files need special handling due to size"
            )

        return results


# Convenience function for quick validation
def validate_document(file_path: str, max_tokens: int = 200_000) -> Tuple[bool, Optional[str]]:
    """
    Quick validation of a document against token budget.

    Args:
        file_path: Path to the document
        max_tokens: Maximum token budget

    Returns:
        Tuple of (can_process, error_message)
    """
    validator = DocumentSizeValidator(max_tokens)
    can_process, error_msg, _ = validator.can_process_document(file_path)
    return can_process, error_msg