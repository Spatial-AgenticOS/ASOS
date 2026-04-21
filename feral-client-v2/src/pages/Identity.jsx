import React from 'react';
import { SelfWorkspace } from '../components/SelfEditors';

/**
 * Identity — standalone route for the IDENTITY / SOUL / MEMORY editors.
 *
 * The actual editors live in ../components/SelfEditors/ so they can also
 * be embedded inside the Settings page's Self section. This page is the
 * canonical /identity route for direct deep-linking.
 *
 * Brain routes touched (unchanged):
 *   GET/POST /api/identity
 *   GET/POST /api/identity/soul
 *   GET      /api/identity/memory_md
 */
export default function Identity() {
  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <SelfWorkspace defaultTab="identity" showIntro />
    </div>
  );
}
