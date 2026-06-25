# ADEPT Prompt Sanitization Implementation Guide

**Version**: 1.0
**Last Updated**: 2025-12-09
**Status**: Active
**Classification**: Internal Use Only

---

## Executive Summary

This guide provides technical implementation details for prompt sanitization in the ADEPT framework. Prompt sanitization is a **defense-in-depth** security control that removes Personally Identifiable Information (PII), Protected Health Information (PHI), and other sensitive data from user prompts **before** they are sent to external LLM providers.

**Why Prompt Sanitization is Critical**:
1. **Contractual Protection**: LLM provider policies prohibit training on paid-tier data, but enforcement is unverifiable
2. **Technical Protection**: Sanitization ensures sensitive data never leaves ADEPT infrastructure
3. **Regulatory Compliance**: HIPAA, GDPR, PCI DSS require data minimization
4. **Risk Mitigation**: Protects against provider policy changes, accidental data exposure, and provider breaches

**Multi-Layer Defense Strategy**:
```
Layer 1: Contractual (DPAs, BAAs) → Legal protection
Layer 2: Provider Selection (Azure OpenAI/AWS Bedrock) → Architectural protection
Layer 3: Prompt Sanitization (This Guide) → Technical protection ✅
Layer 4: Monitoring (Quarterly policy reviews) → Detection and response
```

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Data Classification Matrix](#data-classification-matrix)
3. [Technical Implementation](#technical-implementation)
4. [Integration Points](#integration-points)
5. [Testing and Validation](#testing-and-validation)
6. [Performance Considerations](#performance-considerations)
7. [Operational Procedures](#operational-procedures)
8. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ User Prompt                                                          │
│ "Patient John Doe (SSN: 123-45-6789) has diabetes. Analyze data."  │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Data Classification Check                                            │
│ - Check X-Data-Classification header                                │
│ - Default: "internal" if not specified                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PromptSanitizer (Presidio)                                          │
│ - Analyze: Detect PII/PHI entities                                  │
│ - Anonymize: Redact based on classification level                   │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Sanitized Prompt                                                     │
│ "Patient <PERSON> (SSN: <SSN>) has diabetes. Analyze data."         │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ LLM Provider Selection                                               │
│ - Azure OpenAI Service (preferred)                                  │
│ - AWS Bedrock (alternative)                                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ LLM API Call                                                         │
│ - Sanitized prompt sent to provider                                 │
│ - Original data never leaves ADEPT infrastructure                   │
└─────────────────────────────────────────────────────────────────────┘
```

### System Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **PromptSanitizer** | `orchestration_service/prompt_sanitizer.py` | Core sanitization logic using Presidio |
| **LangChain Agent** | `orchestration_service/scientific_workflow/langchain_agent.py` | Integration point - calls sanitizer before LLM |
| **Data Classification** | Request headers (`X-Data-Classification`) | Determines sanitization level |
| **Logging** | `orchestration_service/logger_config.py` | Audit trail for sanitization events |

---

## Data Classification Matrix

ADEPT uses a four-level data classification system that determines sanitization requirements:

| Classification | Definition | Examples | Sanitization Level | Entities to Redact |
|----------------|------------|----------|--------------------|--------------------|
| **Public** | No harm if disclosed | Open-source code, published papers, public datasets | **None** | N/A |
| **Internal** | Moderate impact if disclosed | Internal workflows, non-sensitive research, operational metrics | **Basic** | EMAIL_ADDRESS, PHONE_NUMBER |
| **Confidential** | Significant impact if disclosed | Business plans, unpublished research, limited PII | **Aggressive** | PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, ORGANIZATION, DATE_TIME |
| **Restricted** | Critical impact if disclosed | PHI, financial data, SSNs, classified research | **Maximum** | All PII/PHI entities (SSN, CREDIT_CARD, MEDICAL_LICENSE, US_PASSPORT, US_DRIVER_LICENSE, IBAN_CODE, IP_ADDRESS, CRYPTO, etc.) |

### Compliance Mapping

| Regulation | Minimum Classification | Sanitization Level |
|------------|------------------------|-------------------|
| **GDPR (EU Personal Data)** | Confidential | Aggressive |
| **HIPAA (Protected Health Information)** | Restricted | Maximum |
| **PCI DSS (Payment Card Data)** | Restricted | Maximum |
| **FedRAMP (Government Data)** | Confidential | Aggressive |
| **CCPA (California Consumer Data)** | Confidential | Aggressive |

---

## Technical Implementation

### File Structure

```
src/agentic_framework_pkg/orchestration_service/
├── prompt_sanitizer.py              # NEW: Core sanitization module
├── scientific_workflow/
│   └── langchain_agent.py           # MODIFY: Integration point
├── logger_config.py                 # MODIFY: Add sanitization logging
└── routers/v1/
    └── threads.py                   # MODIFY: Add X-Data-Classification header support

tests/unit/agentic_framework_pkg/orchestration_service/
└── test_prompt_sanitizer.py         # NEW: Unit tests
```

### Core Implementation: `prompt_sanitizer.py`

```python
# File: src/agentic_framework_pkg/orchestration_service/prompt_sanitizer.py

"""
Prompt Sanitization Module

Removes PII/PHI from user prompts before sending to external LLM providers.
Uses Microsoft Presidio for entity detection and anonymization.

Usage:
    from prompt_sanitizer import PromptSanitizer

    sanitizer = PromptSanitizer()
    sanitized_text = sanitizer.sanitize_for_training_risk(
        prompt="Patient John Doe (SSN: 123-45-6789) has diabetes",
        data_classification="restricted"
    )
    # Output: "Patient <PERSON> (SSN: <SSN>) has diabetes"
"""

import logging
from typing import Dict, List, Optional

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)


class PromptSanitizer:
    """
    Sanitize prompts based on data classification level.

    Supported Classifications:
        - public: No sanitization
        - internal: Basic (EMAIL, PHONE)
        - confidential: Aggressive (PERSON, LOCATION, ORG, DATE)
        - restricted: Maximum (all PII/PHI entities)
    """

    # Entity types by sanitization level
    ENTITY_TYPES = {
        "basic": [
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
        ],
        "aggressive": [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "LOCATION",
            "ORGANIZATION",
            "DATE_TIME",
        ],
        "maximum": [
            # PII entities
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "LOCATION",
            "ORGANIZATION",
            "DATE_TIME",
            # PHI/Financial entities
            "SSN",                      # Social Security Number
            "CREDIT_CARD",              # Credit card numbers
            "MEDICAL_LICENSE",          # Medical license numbers
            "US_PASSPORT",              # US passport numbers
            "US_DRIVER_LICENSE",        # US driver's license
            "US_BANK_NUMBER",           # Bank account numbers
            "IBAN_CODE",                # International bank accounts
            "NRP",                      # National Registry of Persons (various countries)
            # Technical entities
            "IP_ADDRESS",               # IP addresses
            "CRYPTO",                   # Cryptocurrency addresses
            "URL",                      # URLs (may contain tokens)
        ],
    }

    # Classification to sanitization level mapping
    CLASSIFICATION_MAPPING = {
        "public": "none",
        "internal": "basic",
        "confidential": "aggressive",
        "restricted": "maximum",
    }

    def __init__(self):
        """Initialize Presidio engines."""
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()

    def sanitize_for_training_risk(
        self, prompt: str, data_classification: str
    ) -> str:
        """
        Sanitize prompt based on data classification level.

        Args:
            prompt: Original user prompt
            data_classification: One of "public", "internal", "confidential", "restricted"

        Returns:
            Sanitized prompt safe to send to LLM providers

        Raises:
            ValueError: If data_classification is invalid
        """
        if data_classification not in self.CLASSIFICATION_MAPPING:
            raise ValueError(
                f"Invalid data_classification: {data_classification}. "
                f"Must be one of {list(self.CLASSIFICATION_MAPPING.keys())}"
            )

        sanitization_level = self.CLASSIFICATION_MAPPING[data_classification]

        if sanitization_level == "none":
            logger.debug(
                f"Data classification '{data_classification}' requires no sanitization"
            )
            return prompt

        # Get entity types to redact
        entities_to_redact = self.ENTITY_TYPES.get(sanitization_level, [])

        logger.info(
            f"Sanitizing prompt with level='{sanitization_level}', "
            f"entities={len(entities_to_redact)}"
        )

        # Analyze prompt for PII/PHI entities
        analyzer_results = self.analyzer.analyze(
            text=prompt, language="en", entities=entities_to_redact
        )

        if not analyzer_results:
            logger.debug("No PII/PHI entities detected in prompt")
            return prompt

        # Log detected entities (for audit trail)
        detected_entities = [
            f"{result.entity_type}@{result.start}-{result.end}"
            for result in analyzer_results
        ]
        logger.info(
            f"Detected {len(analyzer_results)} PII/PHI entities: {detected_entities}"
        )

        # Anonymize detected entities
        anonymized_result = self.anonymizer.anonymize(
            text=prompt,
            analyzer_results=analyzer_results,
            operators={
                "DEFAULT": OperatorConfig(
                    "replace", {"new_value": "<{entity_type}>"}
                )
            },
        )

        sanitized_prompt = anonymized_result.text

        logger.info(
            f"Sanitization complete: {len(analyzer_results)} entities redacted"
        )
        logger.debug(
            f"Original length: {len(prompt)} chars, "
            f"Sanitized length: {len(sanitized_prompt)} chars"
        )

        return sanitized_prompt

    def get_sanitization_metadata(
        self, prompt: str, data_classification: str
    ) -> Dict[str, any]:
        """
        Get metadata about what would be sanitized without actually sanitizing.

        Useful for testing, auditing, and user feedback.

        Args:
            prompt: Original user prompt
            data_classification: Data classification level

        Returns:
            Dictionary with sanitization metadata:
                - level: Sanitization level applied
                - entities_detected: List of detected entity types
                - entity_count: Number of entities detected
                - would_sanitize: Boolean indicating if sanitization would occur
        """
        sanitization_level = self.CLASSIFICATION_MAPPING.get(
            data_classification, "none"
        )

        if sanitization_level == "none":
            return {
                "level": sanitization_level,
                "entities_detected": [],
                "entity_count": 0,
                "would_sanitize": False,
            }

        entities_to_redact = self.ENTITY_TYPES.get(sanitization_level, [])
        analyzer_results = self.analyzer.analyze(
            text=prompt, language="en", entities=entities_to_redact
        )

        return {
            "level": sanitization_level,
            "entities_detected": [result.entity_type for result in analyzer_results],
            "entity_count": len(analyzer_results),
            "would_sanitize": len(analyzer_results) > 0,
        }
```

---

## Integration Points

### 1. LangChain Agent Integration

**File**: `src/agentic_framework_pkg/orchestration_service/scientific_workflow/langchain_agent.py`

**Modification Point**: Before sending prompts to LLM providers

```python
# MODIFY: Add at top of file
from ..prompt_sanitizer import PromptSanitizer

class ScientificWorkflowAgent:
    def __init__(self, ...):
        # ... existing code ...
        self.prompt_sanitizer = PromptSanitizer()

    async def process_user_message(
        self,
        message: str,
        thread_id: str,
        data_classification: str = "internal",  # NEW parameter
        **kwargs
    ):
        """
        Process user message with prompt sanitization.

        Args:
            message: User's input message
            thread_id: Conversation thread ID
            data_classification: Data sensitivity level
                                 (public, internal, confidential, restricted)
        """
        # NEW: Sanitize prompt before LLM call
        sanitized_message = self.prompt_sanitizer.sanitize_for_training_risk(
            prompt=message,
            data_classification=data_classification
        )

        # Log sanitization for audit trail
        if sanitized_message != message:
            logger.info(
                f"[SANITIZATION] thread_id={thread_id}, "
                f"classification={data_classification}, "
                f"entities_redacted=True"
            )

        # Continue with sanitized message
        response = await self.llm.ainvoke(sanitized_message)
        # ... rest of existing code ...
```

### 2. API Endpoint Integration

**File**: `src/agentic_framework_pkg/orchestration_service/routers/v1/threads.py`

**Modification**: Support `X-Data-Classification` header

```python
# MODIFY: Add header parameter to message creation endpoint

from fastapi import Header

@router.post("/threads/{thread_id}/messages")
async def create_message(
    thread_id: str,
    request: MessageRequest,
    x_data_classification: str = Header(default="internal", alias="X-Data-Classification"),
    # ... existing parameters ...
):
    """
    Create a new message in a thread with optional data classification.

    Headers:
        X-Data-Classification: Data sensitivity level
            - "public": No sanitization
            - "internal": Basic sanitization (email, phone)
            - "confidential": Aggressive sanitization (PII)
            - "restricted": Maximum sanitization (PII + PHI + financial)

    Default: "internal" if not specified
    """
    # Validate classification
    valid_classifications = ["public", "internal", "confidential", "restricted"]
    if x_data_classification not in valid_classifications:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid X-Data-Classification header. "
                   f"Must be one of: {valid_classifications}"
        )

    # Pass classification to agent
    response = await agent.process_user_message(
        message=request.content,
        thread_id=thread_id,
        data_classification=x_data_classification,
    )
    # ... rest of existing code ...
```

### 3. Multi-Agent Session Integration

**File**: `src/agentic_framework_pkg/orchestration_service/multi_agent_manager.py`

**Modification**: Propagate data classification to worker agents

```python
async def create_worker_agent(
    self,
    role: str,
    data_classification: str = "internal",  # NEW parameter
    **kwargs
):
    """Create worker agent with data classification context."""
    worker_agent = ScientificWorkflowAgent(
        # ... existing parameters ...
        data_classification=data_classification,  # Propagate to worker
    )
    # ... rest of existing code ...
```

---

## Testing and Validation

### Unit Tests

**File**: `tests/unit/agentic_framework_pkg/orchestration_service/test_prompt_sanitizer.py`

```python
"""
Unit tests for PromptSanitizer module.

Run:
    pytest tests/unit/agentic_framework_pkg/orchestration_service/test_prompt_sanitizer.py -v
"""

import pytest
from agentic_framework_pkg.orchestration_service.prompt_sanitizer import PromptSanitizer


@pytest.fixture
def sanitizer():
    """Create PromptSanitizer instance for testing."""
    return PromptSanitizer()


class TestPublicClassification:
    """Test public data classification (no sanitization)."""

    def test_public_data_no_sanitization(self, sanitizer):
        """Public data should not be sanitized."""
        prompt = "Patient John Doe (SSN: 123-45-6789) has diabetes"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="public"
        )
        assert result == prompt  # No changes


class TestInternalClassification:
    """Test internal data classification (basic sanitization)."""

    def test_internal_data_redacts_email(self, sanitizer):
        """Internal classification should redact email addresses."""
        prompt = "Contact user@example.com for details"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="internal"
        )
        assert "user@example.com" not in result
        assert "<EMAIL_ADDRESS>" in result

    def test_internal_data_redacts_phone(self, sanitizer):
        """Internal classification should redact phone numbers."""
        prompt = "Call 555-123-4567 for support"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="internal"
        )
        assert "555-123-4567" not in result
        assert "<PHONE_NUMBER>" in result

    def test_internal_data_preserves_names(self, sanitizer):
        """Internal classification should NOT redact person names."""
        prompt = "John Doe requested a meeting"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="internal"
        )
        assert "John Doe" in result  # Names not redacted at basic level


class TestConfidentialClassification:
    """Test confidential data classification (aggressive sanitization)."""

    def test_confidential_data_redacts_person_names(self, sanitizer):
        """Confidential classification should redact person names."""
        prompt = "John Doe and Jane Smith are collaborating"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="confidential"
        )
        assert "John Doe" not in result
        assert "Jane Smith" not in result
        assert "<PERSON>" in result

    def test_confidential_data_redacts_locations(self, sanitizer):
        """Confidential classification should redact locations."""
        prompt = "The meeting is in New York City"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="confidential"
        )
        assert "New York City" not in result
        assert "<LOCATION>" in result

    def test_confidential_data_redacts_organizations(self, sanitizer):
        """Confidential classification should redact organization names."""
        prompt = "Acme Corp is our client"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="confidential"
        )
        assert "Acme Corp" not in result
        assert "<ORGANIZATION>" in result


class TestRestrictedClassification:
    """Test restricted data classification (maximum sanitization)."""

    def test_restricted_data_redacts_ssn(self, sanitizer):
        """Restricted classification should redact SSNs."""
        prompt = "Patient SSN: 123-45-6789"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="restricted"
        )
        assert "123-45-6789" not in result
        assert "<SSN>" in result

    def test_restricted_data_redacts_credit_card(self, sanitizer):
        """Restricted classification should redact credit card numbers."""
        prompt = "Card number: 4532-1234-5678-9010"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="restricted"
        )
        assert "4532-1234-5678-9010" not in result
        assert "<CREDIT_CARD>" in result

    def test_restricted_data_redacts_medical_license(self, sanitizer):
        """Restricted classification should redact medical licenses."""
        prompt = "Dr. Smith's license: MD-123456"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="restricted"
        )
        # Note: Presidio may detect this as MEDICAL_LICENSE or PERSON
        assert "MD-123456" not in result or "Dr. Smith" not in result

    def test_restricted_data_comprehensive_hipaa(self, sanitizer):
        """Restricted classification should handle HIPAA scenario."""
        prompt = (
            "Patient John Doe (DOB: 01/15/1980, SSN: 123-45-6789) "
            "visited clinic at 123 Main St, New York, NY. "
            "Diagnosis: Type 2 Diabetes. "
            "Contact: john.doe@email.com, 555-123-4567"
        )
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="restricted"
        )

        # Verify all PII/PHI is redacted
        assert "John Doe" not in result
        assert "01/15/1980" not in result
        assert "123-45-6789" not in result
        assert "123 Main St" not in result
        assert "john.doe@email.com" not in result
        assert "555-123-4567" not in result

        # Verify clinical information is preserved (no PHI in diagnosis)
        assert "Type 2 Diabetes" in result  # Diagnosis without PHI is preserved


class TestMetadata:
    """Test sanitization metadata functionality."""

    def test_metadata_for_pii_detection(self, sanitizer):
        """Metadata should report detected entities."""
        prompt = "Contact user@example.com or call 555-1234"
        metadata = sanitizer.get_sanitization_metadata(
            prompt=prompt, data_classification="internal"
        )

        assert metadata["level"] == "basic"
        assert metadata["entity_count"] == 2
        assert "EMAIL_ADDRESS" in metadata["entities_detected"]
        assert "PHONE_NUMBER" in metadata["entities_detected"]
        assert metadata["would_sanitize"] is True

    def test_metadata_for_no_pii(self, sanitizer):
        """Metadata should report no entities for clean prompts."""
        prompt = "What is the capital of France?"
        metadata = sanitizer.get_sanitization_metadata(
            prompt=prompt, data_classification="restricted"
        )

        assert metadata["entity_count"] == 0
        assert metadata["entities_detected"] == []
        assert metadata["would_sanitize"] is False


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_invalid_classification_raises_error(self, sanitizer):
        """Invalid data classification should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid data_classification"):
            sanitizer.sanitize_for_training_risk(
                prompt="test", data_classification="invalid"
            )

    def test_empty_prompt_returns_empty(self, sanitizer):
        """Empty prompt should return empty string."""
        result = sanitizer.sanitize_for_training_risk(
            prompt="", data_classification="restricted"
        )
        assert result == ""

    def test_non_english_text_handled_gracefully(self, sanitizer):
        """Non-English text should not cause errors."""
        prompt = "Bonjour Jean Dupont, email: jean@example.fr"
        result = sanitizer.sanitize_for_training_risk(
            prompt=prompt, data_classification="confidential"
        )
        # Should complete without error (may or may not detect non-English PII)
        assert isinstance(result, str)
```

### E2E Integration Test

**File**: `tests/e2e/test_prompt_sanitization_e2e.py`

```python
"""
End-to-end test for prompt sanitization integration.

Tests the full flow: API request → Sanitization → LLM call
"""

import pytest
import httpx
from tests.e2e.test_fixtures_central import get_auth_token


@pytest.mark.asyncio
async def test_e2e_prompt_sanitization_with_restricted_data():
    """Test prompt sanitization with HIPAA-like data."""
    # Get authentication token
    token = await get_auth_token(
        username="notebook-user",
        password="notebook-password"
    )

    base_url = "http://agent_gateway:8081/v1"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create thread
        thread_response = await client.post(
            f"{base_url}/threads",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert thread_response.status_code == 200
        thread_id = thread_response.json()["id"]

        # Send message with restricted data classification
        message_with_phi = (
            "Patient John Doe (SSN: 123-45-6789, DOB: 01/15/1980) "
            "has diabetes. Recommend treatment plan."
        )

        message_response = await client.post(
            f"{base_url}/threads/{thread_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Data-Classification": "restricted",  # Enable max sanitization
            },
            json={
                "role": "user",
                "content": message_with_phi,
            },
        )
        assert message_response.status_code == 200

        # Verify response doesn't echo back PII/PHI
        # (LLM should respond based on sanitized prompt)
        response_content = message_response.json()["content"]
        assert "123-45-6789" not in response_content  # SSN not echoed
        assert "01/15/1980" not in response_content  # DOB not echoed

        # Verify clinical response is still relevant
        assert "diabetes" in response_content.lower()  # Clinical context preserved
```

---

## Performance Considerations

### Latency Impact

**Expected Overhead**:
- **Public classification**: ~0ms (no sanitization)
- **Internal classification**: ~10-50ms (basic entity detection)
- **Confidential classification**: ~50-150ms (full entity detection)
- **Restricted classification**: ~100-300ms (comprehensive PII/PHI detection)

**Optimization Strategies**:

1. **Async Sanitization** (for large prompts):
```python
import asyncio

async def sanitize_async(self, prompt: str, classification: str) -> str:
    """Async wrapper for sanitization (for concurrent processing)."""
    return await asyncio.to_thread(
        self.sanitize_for_training_risk,
        prompt=prompt,
        data_classification=classification
    )
```

2. **Caching Presidio Engines** (singleton pattern):
```python
# Reuse analyzer/anonymizer instances across requests
_analyzer_instance = None

def get_analyzer() -> AnalyzerEngine:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = AnalyzerEngine()
    return _analyzer_instance
```

3. **Batch Processing** (for multi-agent scenarios):
```python
def sanitize_batch(
    self, prompts: List[str], classification: str
) -> List[str]:
    """Sanitize multiple prompts in a single pass."""
    # Presidio supports batch processing for efficiency
    return [
        self.sanitize_for_training_risk(p, classification)
        for p in prompts
    ]
```

### Resource Requirements

**Memory**:
- Presidio models: ~200-500 MB RAM per instance
- Recommendation: 1 GB RAM allocated for sanitization service

**CPU**:
- Entity detection is CPU-bound
- Recommendation: 2+ CPU cores for production workloads

**Scaling**:
- Deploy Presidio as a separate microservice for high-volume scenarios
- Use Redis caching for frequently sanitized prompts

---

## Operational Procedures

### 1. Monitoring and Alerting

**Key Metrics to Track**:

```python
# Log structured data for monitoring
logger.info(
    "[SANITIZATION_METRICS]",
    extra={
        "classification": data_classification,
        "entity_count": len(analyzer_results),
        "latency_ms": (time.time() - start_time) * 1000,
        "prompt_length": len(prompt),
        "sanitized_length": len(sanitized_prompt),
    }
)
```

**CloudWatch/Azure Monitor Alarms**:
- High sanitization latency (>500ms for 95th percentile)
- Sudden increase in detected PII/PHI (potential data leak)
- Sanitization failures (Presidio errors)

### 2. Audit Trail

**Required Logging for Compliance**:

```python
# Log all sanitization events for audit
logger.info(
    f"[AUDIT:SANITIZATION] user_id={user_id}, thread_id={thread_id}, "
    f"classification={data_classification}, entities_redacted={entity_count}, "
    f"timestamp={datetime.utcnow().isoformat()}"
)
```

**Retention**: 90 days (Tier 2), 365 days (Tier 3)

### 3. Quarterly Review

**Review Checklist**:
- [ ] Verify entity detection accuracy (false positives/negatives)
- [ ] Update Presidio models (new entity types, improved accuracy)
- [ ] Review sanitization performance metrics
- [ ] Validate classification mapping (adjust thresholds if needed)
- [ ] Test with real-world prompts from production logs

---

## Troubleshooting

### Common Issues

#### Issue 1: Presidio Not Detecting Entities

**Symptoms**: Known PII/PHI not redacted

**Diagnosis**:
```python
# Check what Presidio detected
metadata = sanitizer.get_sanitization_metadata(prompt, "restricted")
print(f"Detected entities: {metadata['entities_detected']}")
```

**Solutions**:
1. **Add custom recognizers** for domain-specific entities:
```python
from presidio_analyzer import Pattern, PatternRecognizer

# Example: Detect medical record numbers (MRN)
mrn_recognizer = PatternRecognizer(
    supported_entity="MEDICAL_RECORD_NUMBER",
    patterns=[Pattern("MRN", r"MRN-\d{6}", 0.8)]
)
analyzer.registry.add_recognizer(mrn_recognizer)
```

2. **Lower confidence threshold** (trade-off: more false positives):
```python
analyzer_results = self.analyzer.analyze(
    text=prompt,
    language="en",
    entities=entities_to_redact,
    score_threshold=0.5  # Default is 0.7
)
```

#### Issue 2: Over-Redaction (False Positives)

**Symptoms**: Non-sensitive information redacted (e.g., "John Smith" in book titles)

**Solutions**:
1. **Whitelist specific terms**:
```python
# Skip common false positives
WHITELISTED_TERMS = ["John Smith (author)", "Dr. Smith's book"]
if any(term in prompt for term in WHITELISTED_TERMS):
    # Skip sanitization for this section
```

2. **Adjust entity types**:
```python
# Remove overly broad entity types from aggressive/maximum levels
# Example: Remove "ORGANIZATION" if causing false positives
```

#### Issue 3: Performance Degradation

**Symptoms**: Sanitization taking >1 second

**Diagnosis**:
```python
import time

start = time.time()
result = sanitizer.sanitize_for_training_risk(prompt, "restricted")
latency = (time.time() - start) * 1000
logger.warning(f"High sanitization latency: {latency}ms")
```

**Solutions**:
1. **Use faster entity types** (reduce scope):
```python
# Focus on critical entities only for performance
PERFORMANCE_OPTIMIZED_ENTITIES = [
    "SSN", "CREDIT_CARD", "EMAIL_ADDRESS"
]
```

2. **Truncate very long prompts**:
```python
MAX_PROMPT_LENGTH = 10000  # chars
if len(prompt) > MAX_PROMPT_LENGTH:
    prompt = prompt[:MAX_PROMPT_LENGTH]
    logger.warning(f"Truncated prompt to {MAX_PROMPT_LENGTH} chars")
```

3. **Deploy Presidio as separate service** (microservice architecture)

#### Issue 4: Non-English Text Not Detected

**Symptoms**: PII in Spanish, French, etc. not redacted

**Solutions**:
1. **Configure multi-language support**:
```python
# Presidio supports multiple languages
analyzer_results = self.analyzer.analyze(
    text=prompt,
    language="es",  # Spanish
    entities=entities_to_redact
)
```

2. **Use translation for uniform detection**:
```python
# Translate to English → Detect → Translate back
from deep_translator import GoogleTranslator

translated = GoogleTranslator(source="auto", target="en").translate(prompt)
sanitized = self.sanitize_for_training_risk(translated, classification)
# Translate back if needed
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Install Presidio dependencies: `pip install presidio-analyzer presidio-anonymizer`
- [ ] Download Presidio models: `python -m spacy download en_core_web_lg`
- [ ] Create `prompt_sanitizer.py` module
- [ ] Integrate with `langchain_agent.py`
- [ ] Add `X-Data-Classification` header support to API endpoints
- [ ] Write unit tests (target: >80% coverage)
- [ ] Write E2E integration tests

### Post-Deployment

- [ ] Monitor sanitization latency (CloudWatch/Azure Monitor)
- [ ] Set up alerts for high latency (>500ms) or failures
- [ ] Review audit logs weekly (first 4 weeks)
- [ ] Collect false positive/negative reports from users
- [ ] Tune entity recognizers based on production data
- [ ] Document any custom recognizers added
- [ ] Schedule quarterly review with security team

---

## References

1. **Microsoft Presidio Documentation**: https://microsoft.github.io/presidio/
2. **Presidio Analyzer**: https://microsoft.github.io/presidio/analyzer/
3. **Presidio Anonymizer**: https://microsoft.github.io/presidio/anonymizer/
4. **HIPAA Privacy Rule**: https://www.hhs.gov/hipaa/for-professionals/privacy/index.html
5. **GDPR Article 5 (Data Minimization)**: https://gdpr-info.eu/art-5-gdpr/
6. **NIST 800-53 (SC-28: Protection of Information at Rest)**: https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-09 | ADEPT Security & Compliance Team | Initial release |

---

**Document Owner**: ADEPT Security & Compliance Team
**Review Frequency**: Quarterly (align with LLM provider policy review)
**Next Review**: 2025-03-09
**Classification**: Internal Use Only

**Related Documents**:
- `docs/compliance/LLM_PROVIDER_DATA_USAGE_POLICIES.md` - LLM provider policy analysis
- `docs/compliance/ADEPT_COMPLIANCE_REQUIREMENTS_MATRIX.md` - Compliance requirements (Section: "LLM Provider Security Controls")
- `docs/compliance/LLM_PROVIDER_CONTRACT_TEMPLATES.md` - Enhanced DPA templates (planned)
