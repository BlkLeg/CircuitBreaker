import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { adminApi } from '../../api/client.jsx';
import { exportPortableInventory, getTransferSummary } from '../../api/inventoryTransfer';
import { useInventoryTransfer } from '../../hooks/useInventoryTransfer';
import { incomingRow } from '../../lib/inventoryTransfer';
import { useToast } from '../common/Toast';
import Drawer from '../common/Drawer';
import EmptyState from '../common/EmptyState';
import Tabs from '../common/Tabs';
import DecisionsTable from './transfer/DecisionsTable';
import ExportRecoveryCards from './transfer/ExportRecoveryCards';
import ImportFileCard from './transfer/ImportFileCard';
import ImportSteps from './transfer/ImportSteps';
import ResolveDecisionDrawer from './transfer/ResolveDecisionDrawer';
import ReviewPanel from './transfer/ReviewPanel';
import TransferResult from './transfer/TransferResult';
import TransferSummaryTiles from './transfer/TransferSummaryTiles';
import '../../styles/inventory-transfer.css';

const PANEL_TABS = [
  { key: 'import', label: 'Import inventory' },
  { key: 'export', label: 'Export & recovery' },
];

/**
 * The Inventory transfer workbench (plan 02): Settings → System → Data
 * Management. Three artifacts stay honestly distinct — portable export,
 * previewed import (merge only), and full-state snapshot with offline restore.
 * Clear Lab and Factory Reset keep their own safeguards elsewhere in System.
 */
export default function InventoryTransferPanel() {
  const toast = useToast();
  const [tab, setTab] = useState('import');
  const [summary, setSummary] = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [exportDoc, setExportDoc] = useState(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [creatingSnapshot, setCreatingSnapshot] = useState(false);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [drawer, setDrawer] = useState(null); // { conflict, existing }

  const refreshCounts = useCallback(async () => {
    try {
      const res = await getTransferSummary();
      setSummary(res?.data ?? null);
    } catch {
      setSummary(null);
    }
    try {
      const res = await adminApi.listSnapshots();
      const all = res?.data?.snapshots ?? [];
      setSnapshots(all.slice(-5).reverse());
    } catch {
      setSnapshots([]);
    }
  }, []);

  useEffect(() => {
    void refreshCounts();
  }, [refreshCounts]);

  const transfer = useInventoryTransfer({ onApplied: () => void refreshCounts() });

  const loadExport = useCallback(async () => {
    setExportBusy(true);
    try {
      const res = await exportPortableInventory();
      setExportDoc(res?.data ?? null);
    } catch (err) {
      toast.error(err?.message || 'The export could not be prepared.');
      setExportDoc(null);
    } finally {
      setExportBusy(false);
    }
  }, [toast]);

  useEffect(() => {
    if (tab === 'export' && exportDoc === null && !exportBusy) void loadExport();
  }, [tab, exportDoc, exportBusy, loadExport]);

  const latestSnapshot = snapshots[0] ?? null;

  const openConflicts = useMemo(
    () =>
      (transfer.preview?.conflicts ?? []).map((conflict) => ({
        ...conflict,
        row: incomingRow(transfer.document, conflict.entity_type, conflict.source_id),
      })),
    [transfer.preview, transfer.document]
  );

  const handleResolve = useCallback((conflict, existing) => setDrawer({ conflict, existing }), []);

  const handleSaveDecision = useCallback(
    async (decision) => {
      if (!drawer?.conflict) return null;
      return transfer.saveDecision(drawer.conflict, decision);
    },
    [drawer, transfer]
  );

  const createSnapshot = useCallback(async () => {
    setCreatingSnapshot(true);
    try {
      await adminApi.triggerSnapshot();
      toast.success('Snapshot created.');
      await refreshCounts();
    } catch (err) {
      toast.error(err?.message || 'The snapshot could not be created.');
    } finally {
      setCreatingSnapshot(false);
    }
  }, [toast, refreshCounts]);

  const handleModeChange = useCallback((event) => {
    if (event.target.value === 'replace') {
      setReplaceOpen(true);
      event.target.value = 'merge';
    }
  }, []);

  return (
    <div className="inv-transfer" id="inventory-transfer">
      <header className="inv-transfer__head">
        <h3 className="inv-transfer__title">Inventory transfer</h3>
        <p className="inv-transfer__subtitle">
          Validate every record and relationship before applying changes.
        </p>
      </header>
      <TransferSummaryTiles summary={summary} snapshot={latestSnapshot} />
      <Tabs tabs={PANEL_TABS} active={tab} onChange={setTab} label="Inventory transfer views" />
      {tab === 'import' ? (
        <div className="inv-transfer__import">
          <ImportFileCard
            fileName={transfer.fileName}
            format={transfer.document?.format}
            version={transfer.document?.version}
            documentEntities={transfer.documentEntities}
            documentRelationships={transfer.documentRelationships}
            preview={transfer.preview}
            busy={transfer.busy}
            error={transfer.step === 'validate' ? transfer.error : null}
            onFileSelected={transfer.selectFile}
            onRemoveFile={transfer.removeFile}
          />
          {transfer.document ? (
            <>
              <label className="inv-transfer__mode">
                <span>Import operation</span>
                <select defaultValue="merge" onChange={handleModeChange}>
                  <option value="merge">Merge into this inventory</option>
                  <option value="replace">Replace inventory…</option>
                </select>
              </label>
              <p className="inv-transfer__mode-note">
                Incoming identifiers are remapped. Existing records are preserved unless you
                explicitly match them.
              </p>
            </>
          ) : null}
          {transfer.document ? (
            <ImportSteps
              current={transfer.step}
              hasDocument={Boolean(transfer.document)}
              applying={transfer.applying}
            />
          ) : null}
          {transfer.step === 'resolve' && transfer.preview ? (
            <section className="inv-transfer__stage" aria-label="Resolve decisions">
              <div
                className={`inv-alert ${openConflicts.length === 0 ? 'inv-alert--ok' : 'inv-alert--warn'}`}
                role="status"
              >
                <strong>
                  {openConflicts.length === 0
                    ? 'All decisions are recorded'
                    : `${openConflicts.length} record${openConflicts.length === 1 ? '' : 's'} need${
                        openConflicts.length === 1 ? 's' : ''
                      } your attention`}
                </strong>
                <p>
                  {openConflicts.length === 0
                    ? 'Review the proposed changes before applying.'
                    : 'Resolve names and references before anything is changed.'}
                </p>
              </div>
              <DecisionsTable
                conflicts={openConflicts}
                decisions={transfer.decisions}
                onResolve={handleResolve}
              />
              <div className="inv-transfer__stagefoot">
                <span className="inv-transfer__footnote">No changes have been applied</span>
                <span className="inv-transfer__footnote">
                  {transfer.resolvedCount} resolved · {transfer.documentRelationships} relationships
                  checked
                </span>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!transfer.preview.can_apply || transfer.busy}
                  onClick={transfer.goReview}
                >
                  Review changes
                </button>
              </div>
            </section>
          ) : null}
          {transfer.step === 'review' && transfer.preview ? (
            <section className="inv-transfer__stage" aria-label="Review the transfer">
              <ReviewPanel
                preview={transfer.preview}
                applying={transfer.applying}
                error={transfer.error}
                onApply={() => void transfer.apply()}
                onBack={transfer.backToResolve}
                onRevalidate={() => void transfer.revalidate()}
              />
            </section>
          ) : null}
          {transfer.step === 'result' && transfer.result ? (
            <section className="inv-transfer__stage" aria-label="Transfer result">
              <TransferResult
                result={transfer.result}
                fileName={transfer.fileName}
                onReset={transfer.reset}
              />
            </section>
          ) : null}
          {transfer.step === 'validate' && !transfer.document ? (
            <div className="inv-transfer__recovery-note">
              <p>
                Recovering your whole instance? Use a full-state snapshot and the offline restore
                workflow.
              </p>
              <button type="button" className="btn btn-sm" onClick={() => setTab('export')}>
                View recovery options
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <ExportRecoveryCards
          exportDoc={exportDoc}
          exportBusy={exportBusy}
          snapshot={latestSnapshot}
          creatingSnapshot={creatingSnapshot}
          onCreateSnapshot={() => void createSnapshot()}
        />
      )}
      {summary === null && tab === 'import' ? (
        <EmptyState
          message="Inventory counts are unavailable right now."
          hint="Reload the page to try again."
        />
      ) : null}
      <ResolveDecisionDrawer
        open={drawer !== null}
        conflict={drawer?.conflict ?? null}
        existingDecision={drawer?.existing ?? null}
        document={transfer.document}
        busy={transfer.busy}
        error={transfer.error}
        onSave={handleSaveDecision}
        onClose={() => setDrawer(null)}
      />
      <Drawer isOpen={replaceOpen} onClose={() => setReplaceOpen(false)} title="Replace inventory">
        <div className="inv-replace">
          <div className="inv-alert inv-alert--warn" role="alert">
            <TriangleAlert aria-hidden="true" />
            <div>
              <strong>This replaces the current inventory</strong>
              <p>
                A verified safety snapshot and an explicit replacement preview are required. Merge
                is the default for bringing another lab into this instance.
              </p>
            </div>
          </div>
          <p className="inv-replace__note">
            Replacement is not part of this release. Whole-instance recovery is the offline restore
            workflow — see Export &amp; recovery.
          </p>
          <button type="button" className="btn btn-primary" onClick={() => setReplaceOpen(false)}>
            Return to merge
          </button>
        </div>
      </Drawer>
    </div>
  );
}
