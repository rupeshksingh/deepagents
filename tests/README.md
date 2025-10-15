# Deep Agents Test Suite

Comprehensive evaluation system for the Danish Tender Analysis Agent (SKI 02.15).

## Overview

This test suite validates:
- **L1/L2/L3 Progressive Disclosure**: Efficient information access patterns
- **Language-Aware RAG**: Danish/English adaptive search
- **Subagent Delegation**: Document Analyzer and Web Researcher coordination
- **Human-in-the-Loop (HITL)**: Contradiction detection and clarification
- **Architecture Guardrails**: Single-tender scope, citation discipline, artifact management
- **Performance**: Response times and resource utilization

## Test Structure

### Test Categories

1. **L1_Simple** (🟢): Quick metadata/filesystem access, no RAG
2. **L2_Targeted** (🟡): Semantic search with language adaptation
3. **L3_Deep** (🟠): Full document retrieval and deep analysis
4. **Subagent_Delegation** (🟠): Complex multi-document analysis with subagents
5. **HITL** (🟠): Human-in-the-loop scenarios
6. **Research_Hybrid** (🔴): Internal + external web research
7. **Architecture_Guardrails** (⚪): System behavior validation

### Complexity Levels

- **Simple** 🟢: Single tool call, <10s, straightforward validation
- **Moderate** 🟡: Multiple tool calls, L2 search, 10-30s
- **Advanced** 🟠: Subagent delegation, multi-document, 30-120s
- **Research+** 🔴: Hybrid internal/external, complex synthesis, >120s

### Test Count: 30 High-Quality Tests

Quality over quantity. Each test validates unique architectural capabilities.

## Quick Start

### 1. List All Tests

```bash
cd tests
python test_runner.py --list
```

### 2. List Tests by Category

```bash
python test_runner.py --list --category L1_Simple
python test_runner.py --list --category Subagent_Delegation
```

### 3. Run Specific Tests by ID

```bash
# Run single test
python test_runner.py L1-01

# Run multiple tests
python test_runner.py L1-01 L2-01 SUB-01

# Run with spaces
python test_runner.py L1-01 L1-02 L2-01 L3-01
```

### 4. Run All Tests of a Complexity Level

```bash
# Run all simple tests
python test_runner.py --complexity Simple

# Run all moderate tests
python test_runner.py --complexity Moderate

# Run all advanced tests
python test_runner.py --complexity Advanced
```

### 5. Run All Tests (Full Suite)

```bash
python test_runner.py --all
```

## Test IDs Reference

### L1 - Simple (Quick Lookups)
- **L1-01**: Submission deadline and modality
- **L1-02**: Framework mechanism - mini-tender prohibition

### L2 - Targeted (Semantic Search)
- **L2-01**: Evaluation criteria and weights (with language adaptation)
- **L2-02**: Mandatory vs optional service areas

### L3 - Deep (Full Document Analysis)
- **L3-01**: CSR international frameworks - verbatim extraction
- **L3-02**: Personnel replacement procedure and costs

### SUB - Subagent Delegation
- **SUB-01**: SLA metrics with cross-document comparison
- **SUB-02**: Deliverables checklist for multiple service areas

### HITL - Human-in-the-Loop
- **HITL-01**: Conflicting information - email address discrepancy
- **HITL-02**: Ambiguous scope - advisory vs execution balance

### WEB - Research Hybrid
- **WEB-01**: GDPR Article 28 mapping (external + internal)
- **WEB-02**: Customer verification with external CVR check

### ARCH - Architecture Guardrails
- **ARCH-01**: Single-tender scope enforcement
- **ARCH-02**: Citation discipline - no file_id exposure
- **ARCH-03**: Language adaptation observable behavior
- **ARCH-04**: Artifact management - file creation

### FIN - Finance
- **FIN-01**: Monthly reporting obligations and penalties
- **FIN-02**: Burden of proof - sales outside framework

### WRITE - Bid Writing
- **WRITE-01**: CSR response outline with tender alignment
- **WRITE-02**: Draft IT procurement approach text

### SME - Subject Matter Expert
- **SME-01**: Skal vs Bør - must vs should requirements
- **SME-02**: Deep dive - IT architecture sub-areas
- **SME-03**: License advisory scope with language adaptation

### LEG - Legal
- **LEG-01**: Liability cap and exclusions
- **LEG-02**: Termination rights, notices, and cure periods
- **LEG-03**: No contractual changes at award stage

### PERF - Performance
- **PERF-01**: Performance test - simple L1 query speed
- **PERF-02**: Performance test - complex multi-document analysis

### EDGE - Edge Cases
- **EDGE-01**: Edge case - ambiguous query clarification
- **EDGE-02**: Edge case - information not in tender

### COMPLEX - Comprehensive Workflows
- **COMPLEX-01**: Comprehensive sustainability analysis with CSRD benchmarking

## Output Structure

Each test run creates:

```
tests/results/run_YYYYMMDD_HHMMSS/
├── summary_report.txt          # Overall results and statistics
├── L1-01_output.txt           # Individual test detailed output
├── L2-01_output.txt
└── ...
```

### Summary Report Contains:
- Overall pass/fail statistics
- Total duration and tool call counts
- Breakdown by category
- Failed validation criteria for each failed test

### Individual Test Output Contains:
- Test metadata and configuration
- Execution summary with timing
- Tool usage breakdown
- Validation results (passed/failed criteria)
- Agent thinking (session log)
- Final response

## Validation Criteria

Each test includes:

1. **Success Criteria**: Expected behaviors and content
2. **Must Cite**: Required source citations
3. **Must Not**: Forbidden behaviors (e.g., exposing file_id)
4. **Regex Validation**: Pattern matching for format compliance
5. **Log Validation**: Tool call sequences and language markers
6. **Performance Thresholds**: Maximum response times

## Example Workflows

### Quick Sanity Check (Run Simple Tests)
```bash
python test_runner.py --complexity Simple
```

### Architecture Validation (Run Guardrails)
```bash
python test_runner.py ARCH-01 ARCH-02 ARCH-03 ARCH-04
```

### Full L1→L2→L3 Progression
```bash
python test_runner.py L1-01 L2-01 L3-01
```

### Subagent Coordination Test
```bash
python test_runner.py SUB-01 SUB-02 WEB-01
```

### Performance Regression Test
```bash
python test_runner.py PERF-01 PERF-02
```

### Legal and Compliance Deep Dive
```bash
python test_runner.py LEG-01 LEG-02 LEG-03 FIN-01 FIN-02
```

## Adding New Tests

### 1. Edit `test_cases.json`

```json
{
  "id": "NEW-01",
  "name": "Your Test Name",
  "category": "L2_Targeted",
  "persona": "Bid Writer",
  "complexity": "Moderate",
  "query_en": "Your English query",
  "query_da": "Your Danish query (optional)",
  "architecture_focus": ["L2_search", "language_adaptation"],
  "expected_routing": "L1 → L2 → Response",
  "success_criteria": [
    "First expected behavior",
    "Second expected behavior"
  ],
  "must_cite": ["Bilag X"],
  "key_facts": ["fact_1", "fact_2"]
}
```

### 2. Test Your New Test

```bash
python test_runner.py NEW-01
```

### 3. Update Test Count

Remember to increment `total_tests` in the metadata section of `test_cases.json`.

## CI/CD Integration

```bash
# Run core regression suite (fast)
python test_runner.py L1-01 L1-02 L2-01 ARCH-01 ARCH-02 ARCH-03

# Run full suite (slow, for nightly builds)
python test_runner.py --all

# Exit code: 0 if all pass, 1 if any fail
```

## Troubleshooting

### Test Not Found
```
❌ Test ID not found: XYZ-99
```
→ Run `python test_runner.py --list` to see valid test IDs

### Environment Variables Missing
```
❌ TENDER_ID not found in environment
```
→ Ensure `.env` file has `MONGODB_URL` and `TENDER_ID`

### Validation Failures
Check the individual test output file for detailed validation results and failed criteria.

## Test Philosophy

- **Quality > Quantity**: 30 carefully designed tests > 100 superficial tests
- **Architectural Focus**: Each test validates specific architectural capabilities
- **Real-World Scenarios**: Tests based on actual bid team personas and workflows
- **Observable Behavior**: Validates tool calls, logs, and output formats
- **Deterministic**: Same input → same expected behavior

## Maintenance

### Regular Updates
1. Add tests for new features
2. Update success criteria when architecture changes
3. Remove obsolete tests
4. Keep test count manageable (<50 tests)

### Quality Checks
- Run full suite weekly
- Review failed tests for false positives
- Update validation logic as needed
- Document architectural changes in test descriptions

---

**Version**: 1.0  
**Last Updated**: October 2025  
**Maintained By**: Pentimenti Development Team

