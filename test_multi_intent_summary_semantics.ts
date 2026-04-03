import { extractAgentResult } from './frontend/src/lib/agentResultExtractor.ts';
import { formatAgentMarkdown, buildResultCardProps } from './frontend/src/lib/agentFormatters.ts';

const BASE_URL = process.env.BASE_URL || 'http://localhost:5000';
const RUNS = Number(process.env.RUNS || 20);

const requestBody = {
  request:
    'IT department needs $45 for office supplies from Office Depot - check budget, assess risk, recommend vendor, and route approval',
  pr_data: {
    department: 'IT',
    budget: 45,
    budget_category: 'OPEX',
    category: 'Office Supplies',
  },
};

function assertNoFalseFailure(markdown: string, verdict: string) {
  const hasFailedLine = /\*\*\d+ failed\*\*/i.test(markdown);
  const riskMarkedFailed = /\*\*2\. .*Risk Assessment\*\*[\s\S]*?\n\s*❌\s*\*\*Result:/i.test(markdown);
  const verdictFailed = /FAILED/i.test(verdict);

  if (hasFailedLine || riskMarkedFailed || verdictFailed) {
    throw new Error(
      `False failure detected. verdict="${verdict}", hasFailedLine=${hasFailedLine}, riskMarkedFailed=${riskMarkedFailed}`,
    );
  }
}

async function runOnce(index: number): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/agentic/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status} from backend`);
  }

  const raw = await res.json();
  const normalised = extractAgentResult(raw, raw?.agent || 'Agent');
  const markdown = formatAgentMarkdown(normalised);
  const card = buildResultCardProps(normalised);

  assertNoFalseFailure(markdown, card.verdict);

  const completedLine = markdown.split('\n').find((l) => l.includes('completed')) || '-';
  const followupLine = markdown.split('\n').find((l) => l.includes('require follow-up')) || '-';
  console.log(`[${index}] PASS | verdict=${card.verdict} | ${completedLine.trim()} | ${followupLine.trim()}`);
}

async function main() {
  console.log('='.repeat(80));
  console.log('MULTI-INTENT SUMMARY SEMANTICS TEST');
  console.log('='.repeat(80));
  console.log(`Base URL: ${BASE_URL}`);
  console.log(`Runs: ${RUNS}`);

  let passed = 0;
  let failed = 0;

  for (let i = 1; i <= RUNS; i++) {
    try {
      await runOnce(i);
      passed += 1;
    } catch (err) {
      failed += 1;
      console.log(`[${i}] FAIL | ${(err as Error).message}`);
    }
  }

  console.log('-'.repeat(80));
  console.log(`Summary: passed=${passed}, failed=${failed}, passRate=${((passed / RUNS) * 100).toFixed(1)}%`);
  if (failed > 0) {
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
