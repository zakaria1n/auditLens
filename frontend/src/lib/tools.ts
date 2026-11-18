/**
 * Étiquettes lisibles des tools (docs/02 — « Lire les commandes ERP » etc.).
 * Le nom interne reste toujours affiché à côté : aucune invention de capacité.
 */
const TOOL_LABELS: Record<string, string> = {
  odoo_read_orders: 'Lire les commandes ERP',
  odoo_read_invoices: 'Lire les factures ERP',
  odoo_read_stock: 'Lire le stock ERP',
  api_inspect_contract: 'Vérifier le contrat API',
  api_fetch_records: 'Extraire des enregistrements API',
  web_run_journey: 'Contrôler un parcours web',
  web_trace: 'Tracer une page web',
  data_profile: 'Analyser les données',
  data_validate: 'Valider les données (contrat)',
  evidence_join: 'Recouper les preuves',
  evidence_search: 'Rechercher dans une preuve',
  odoo_cross_check: 'Réconcilier commandes / factures / stock',
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}
