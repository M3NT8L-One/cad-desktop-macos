/** Catalog title blocks (GET /v1/drawing-templates). Company names stay in the catalog payload. */

import { api } from '@/lib/api';
import { py } from './code';

export interface CatalogTemplate {
  id: string;
  label: string;
  default: boolean;
  standard?: 'ISO' | 'ANSI';
  sheet?: string;
  orientation?: string;
  projection?: string;
  units?: string;
  dual_units?: string;
  fields: string[];
  logo: boolean;
}

export interface DrawingCatalog {
  templates: CatalogTemplate[];
  default: string | null;
}

let catalog: DrawingCatalog = { templates: [], default: null };

export function drawingCatalog(): DrawingCatalog {
  return catalog;
}

/** Load the catalog. A missing route or an empty company directory leaves the built-in block. */
export async function loadDrawingCatalog(): Promise<DrawingCatalog> {
  try {
    const next = await api<DrawingCatalog>('/v1/drawing-templates');
    if (next && Array.isArray(next.templates)) catalog = next;
  } catch { /* Offline or an older server: new sheets keep the built-in block. */ }
  return catalog;
}

/**
 * Arguments for a new sheet. `mode` is the account setting `drawing.defaultTemplate`:
 * `'catalog'` (the default) preselects the catalog's default template, `''` forces the built-in block,
 * and any other string pins that id. Undefined when the built-in block should be written (no `template=`).
 */
export function defaultSheetChanges(mode: string | undefined): Record<string, string> | undefined {
  if (mode === '') return undefined;
  const id = !mode || mode === 'catalog' ? catalog.default : mode;
  const item = id ? catalog.templates.find((template) => template.id === id) : undefined;
  if (!item) return undefined;
  const changes: Record<string, string> = { template: py(item.id) };
  if (item.standard) changes.standard = py(item.standard);
  if (item.sheet) changes.sheet = py(item.sheet);
  if (item.orientation && item.orientation !== 'landscape') changes.orientation = py(item.orientation);
  if (item.projection) changes.projection = py(item.projection);
  if (item.units) changes.units = py(item.units);
  if (item.dual_units) changes.dual_units = py(item.dual_units);
  return changes;
}
