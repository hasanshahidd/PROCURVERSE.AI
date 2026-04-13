/**
 * Result Card - Structured chat bubble for agent responses
 * Shows agent name, confidence, verdict, score, findings, and pipeline toggle
 */

import { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronDown, ChevronUp, AlertTriangle, CheckCircle, Info, AlertCircle } from 'lucide-react';
import { Button } from './ui/button';

interface Finding {
  severity: 'error' | 'warning' | 'success' | 'info';
  message: string;
}

interface Score {
  total: number;
  subscores?: {
    quality?: number;
    price?: number;
    delivery?: number;
    category?: number;
    vendor?: number;
    financial?: number;
    compliance?: number;
    operational?: number;
  };
}

interface ResultCardProps {
  agent: string;
  confidence: number;
  executionTimeMs: number;
  verdict: string;
  dataSource?: string;
  score?: Score;
  findings: Finding[];
  approvalChain?: Array<{
    level: number;
    approver: string;
    email: string;
    status: string;
  }>;
  onShowPipeline?: () => void;
  onViewApprovalChain?: () => void;
}

export function ResultCard({
  agent,
  confidence,
  executionTimeMs,
  verdict,
  dataSource,
  score,
  findings,
  approvalChain,
  onShowPipeline,
  onViewApprovalChain,
}: ResultCardProps) {
  const [expanded, setExpanded] = useState(true);

  // Determine verdict type for styling
  const verdictType = getVerdictType(verdict);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl shadow-md border overflow-hidden bg-gradient-to-r from-blue-50 to-blue-100 dark:from-blue-950/40 dark:to-blue-900/30"
    >
      {/* Header */}
      <div className="p-4 bg-gradient-to-r from-blue-100 to-blue-50 dark:from-blue-900/50 dark:to-blue-950/40 border-b border-blue-200 dark:border-blue-800/50">
        <div className="flex items-start justify-between gap-3">
          {/* Agent Info */}
          <div className="flex items-center gap-2 flex-1">
            <span className="px-3 py-1 bg-gradient-to-r from-blue-500/20 to-purple-500/20 text-blue-700 dark:text-blue-400 text-xs font-semibold rounded-full border border-blue-500/30">
              {agent}
            </span>
            {dataSource && (
              <span className="px-2 py-0.5 text-[11px] font-medium rounded border bg-slate-50 text-slate-700 border-slate-200 dark:bg-slate-900/40 dark:text-slate-200 dark:border-slate-700">
                Data Source: {dataSource}
              </span>
            )}
            <span className={`px-2 py-0.5 text-xs font-medium rounded ${getConfidenceBadge(confidence)}`}>
              {(confidence * 100).toFixed(0)}% confidence
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-500">{executionTimeMs}ms</span>
          </div>

          {/* Expand/Collapse */}
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1 hover:bg-slate-200 dark:hover:bg-slate-700 rounded transition-colors"
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4 text-slate-600 dark:text-slate-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-slate-600 dark:text-slate-400" />
            )}
          </button>
        </div>
      </div>

      {/* Verdict Banner */}
      <div className={`px-4 py-3 font-semibold text-center ${getVerdictBannerColor(verdictType)}`}>
        {verdict}
      </div>

      {/* Expandable Content */}
      {expanded && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="border-t border-slate-200 dark:border-slate-700"
        >
          {/* Score Bar */}
          {score && (
            <div className="p-4 border-b border-slate-200 dark:border-slate-700">
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-600 dark:text-slate-400 font-medium">Overall Score</span>
                <span className="text-slate-900 dark:text-white font-semibold">{score.total}/100</span>
              </div>
              <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-3 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${score.total}%` }}
                  transition={{ duration: 1, ease: 'easeOut' }}
                  className={`h-3 rounded-full ${getScoreBarColor(score.total)}`}
                />
              </div>

              {/* Subscores */}
              {score.subscores && Object.keys(score.subscores).length > 0 && (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {Object.entries(score.subscores).map(([key, value]) => (
                    <div key={key} className="flex justify-between text-xs">
                      <span className="text-slate-600 dark:text-slate-400 capitalize">{key}</span>
                      <span className="text-slate-800 dark:text-slate-300 font-medium">{value}/100</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Findings List */}
          {findings.length > 0 && (
            <div className="p-4 space-y-2">
              {findings.map((finding, idx) => (
                <div
                  key={idx}
                  className={`flex items-start gap-3 p-3 rounded-lg ${getFindingBackground(finding.severity)}`}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    {finding.severity === 'error' && <AlertCircle className="w-5 h-5 text-red-400" />}
                    {finding.severity === 'warning' && <AlertTriangle className="w-5 h-5 text-amber-400" />}
                    {finding.severity === 'success' && <CheckCircle className="w-5 h-5 text-green-400" />}
                    {finding.severity === 'info' && <Info className="w-5 h-5 text-blue-400" />}
                  </div>
                  <div className="flex-1">
                    <p className={`text-sm ${getFindingTextColor(finding.severity)}`}>
                      {finding.message}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Action Buttons — only rendered if at least one action is provided.
              Sprint B: `/process` page is deleted, so ChatPage no longer passes
              onShowPipeline. Approval-chain action remains optional. */}
          {(onShowPipeline || (approvalChain && approvalChain.length > 0 && onViewApprovalChain)) && (
            <div className="p-4 border-t border-blue-200 dark:border-blue-800/50 flex gap-2">
              {onShowPipeline && (
                <Button
                  onClick={onShowPipeline}
                  variant="outline"
                  size="sm"
                  className="flex-1 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white border-0 shadow-sm transition-all"
                >
                  <svg
                    className="w-4 h-4 mr-2"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                    />
                  </svg>
                  Show Pipeline
                </Button>
              )}

              {approvalChain && approvalChain.length > 0 && onViewApprovalChain && (
                <Button
                  onClick={onViewApprovalChain}
                  variant="outline"
                  size="sm"
                  className="flex-1 bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 border-purple-500/30"
                >
                  <svg
                    className="w-4 h-4 mr-2"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  View Approval Chain
                </Button>
              )}
            </div>
          )}
        </motion.div>
      )}
    </motion.div>
  );
}

// Helper functions
function getVerdictType(verdict: string): 'success' | 'error' | 'warning' | 'info' {
  const lowerVerdict = verdict.toLowerCase();
  if (lowerVerdict.includes('approved') || lowerVerdict.includes('success') || lowerVerdict.includes('pass') || lowerVerdict.includes('completed') || lowerVerdict.includes('routed') || lowerVerdict.includes('recommended')) {
    return 'success';
  }
  if (lowerVerdict.includes('rejected') || lowerVerdict.includes('violation') || lowerVerdict.includes('fail') || lowerVerdict.includes('insufficient') || lowerVerdict.includes('blocked') || lowerVerdict.includes('high_risk')) {
    return 'error';
  }
  if (lowerVerdict.includes('warning') || lowerVerdict.includes('review') || lowerVerdict.includes('escalate') || lowerVerdict.includes('medium_risk') || lowerVerdict.match(/\d+\/\d+/)) {
    return 'warning';
  }
  return 'info';
}

function getVerdictBannerColor(type: 'success' | 'error' | 'warning' | 'info'): string {
  const colors = {
    success: 'bg-green-500/20 text-green-700 dark:text-green-400 border-t border-green-500/30',
    error: 'bg-red-500/20 text-red-700 dark:text-red-400 border-t border-red-500/30',
    warning: 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-t border-amber-500/30',
    info: 'bg-blue-500/20 text-blue-700 dark:text-blue-400 border-t border-blue-500/30',
  };
  return colors[type];
}

function getConfidenceBadge(confidence: number): string {
  if (confidence >= 0.8) {
    return 'bg-green-500/20 text-green-700 dark:text-green-400 border border-green-500/30';
  }
  if (confidence >= 0.6) {
    return 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border border-amber-500/30';
  }
  return 'bg-red-500/20 text-red-700 dark:text-red-400 border border-red-500/30';
}

function getScoreBarColor(score: number): string {
  if (score >= 80) return 'bg-gradient-to-r from-green-500 to-emerald-400';
  if (score >= 60) return 'bg-gradient-to-r from-blue-500 to-cyan-400';
  if (score >= 40) return 'bg-gradient-to-r from-amber-500 to-yellow-400';
  return 'bg-gradient-to-r from-red-500 to-orange-400';
}

function getFindingBackground(severity: 'error' | 'warning' | 'success' | 'info'): string {
  const backgrounds = {
    error: 'bg-red-500/10 border border-red-500/20',
    warning: 'bg-amber-500/10 border border-amber-500/20',
    success: 'bg-green-500/10 border border-green-500/20',
    info: 'bg-blue-500/10 border border-blue-500/20',
  };
  return backgrounds[severity];
}

function getFindingTextColor(severity: 'error' | 'warning' | 'success' | 'info'): string {
  const colors = {
    error: 'text-red-700 dark:text-red-300',
    warning: 'text-amber-700 dark:text-amber-300',
    success: 'text-green-700 dark:text-green-300',
    info: 'text-blue-700 dark:text-blue-300',
  };
  return colors[severity];
}
