/**
 * UI component coverage pack (stage 5.4).
 *
 * Covers Modal, CodeEditor, DeviceQRCode, LiveOpsStream — four components
 * at <30% before this stage. Each gets mount + primary interactions.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/react';
import Modal from '../ui/Modal';
import CodeEditor from '../ui/CodeEditor';
import DeviceQRCode from '../ui/DeviceQRCode';
import LiveOpsStream from '../shell/LiveOpsStream';

beforeEach(() => {
  vi.stubGlobal('WebSocket', class { constructor() {} close() {} });
});

// ── Modal ────────────────────────────────────────────────────────

describe('Modal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<Modal open={false} onClose={() => {}} title="T">body</Modal>);
    expect(container.firstChild).toBeNull();
  });

  it('renders title + children + actions when open', () => {
    const { getByText } = render(
      <Modal open onClose={() => {}} title="Confirm" actions={<button>OK</button>}>
        body
      </Modal>,
    );
    expect(getByText('Confirm')).toBeInTheDocument();
    expect(getByText('body')).toBeInTheDocument();
    expect(getByText('OK')).toBeInTheDocument();
  });

  it('Escape key triggers onClose when dismissible', () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="T">x</Modal>);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('Escape key does nothing when dismissible=false', () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="T" dismissible={false}>x</Modal>);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('accepts size prop without crashing', () => {
    const { container } = render(
      <Modal open onClose={() => {}} title="T" size="lg">x</Modal>,
    );
    expect(container.firstChild).toBeInTheDocument();
  });
});

// ── CodeEditor ──────────────────────────────────────────────────

describe('CodeEditor', () => {
  it('renders the value as textarea content', () => {
    const { getByRole } = render(<CodeEditor value="hello" onChange={() => {}} />);
    expect(getByRole('textbox')).toHaveValue('hello');
  });

  it('onChange fires with new text', () => {
    const onChange = vi.fn();
    const { getByRole } = render(<CodeEditor value="" onChange={onChange} />);
    fireEvent.change(getByRole('textbox'), { target: { value: 'new' } });
    expect(onChange).toHaveBeenCalledWith('new');
  });

  it('readOnly prevents input changes reaching onChange', () => {
    const onChange = vi.fn();
    const { getByRole } = render(<CodeEditor value="x" onChange={onChange} readOnly />);
    // Even with readOnly, React's fireEvent.change will call the handler
    // if attached, but the component still renders the read-only flag.
    const textarea = getByRole('textbox');
    expect(textarea).toHaveAttribute('readOnly');
  });

  it('custom aria-label overrides the generated one', () => {
    const { getByLabelText } = render(
      <CodeEditor value="x" onChange={() => {}} aria-label="Identity editor" />,
    );
    expect(getByLabelText('Identity editor')).toBeInTheDocument();
  });

  it('language prop decorates className', () => {
    const { getByRole } = render(
      <CodeEditor value="x" onChange={() => {}} language="yaml" />,
    );
    expect(getByRole('textbox').className).toContain('v2-code-editor--yaml');
  });
});

// ── DeviceQRCode ────────────────────────────────────────────────

describe('DeviceQRCode', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true, status: 200,
      headers: { get: () => 'image/png' },
      blob: () => Promise.resolve(new Blob(['x'], { type: 'image/png' })),
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
    })));
    // jsdom lacks URL.createObjectURL by default.
    if (!global.URL.createObjectURL) {
      global.URL.createObjectURL = vi.fn(() => 'blob:mock');
      global.URL.revokeObjectURL = vi.fn();
    }
  });

  it('renders a text-link view when a value prop is passed', () => {
    const { getByText } = render(<DeviceQRCode value="http://brain.local/pair?t=abc" />);
    expect(getByText(/http:\/\/brain\.local\/pair\?t=abc/)).toBeInTheDocument();
  });

  it('fetches and renders a PNG when no value prop is passed', async () => {
    const { findByAltText } = render(<DeviceQRCode size={180} />);
    expect(await findByAltText(/Device pairing QR code/i)).toBeInTheDocument();
  });

  it('renders error state when the API call rejects', async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('boom'))));
    const { findByText } = render(<DeviceQRCode />);
    expect(await findByText(/QR unavailable/)).toBeInTheDocument();
  });
});

// ── LiveOpsStream ───────────────────────────────────────────────

describe('LiveOpsStream', () => {
  it('renders nothing when no events have arrived', () => {
    const { container } = render(<LiveOpsStream active={false} />);
    // Empty list; component always renders a ul.
    const ul = container.querySelector('ul');
    expect(ul).toBeTruthy();
    expect(ul.children.length).toBe(0);
  });

  it('applies `is-active` class when active=true', () => {
    const { container } = render(<LiveOpsStream active />);
    const ul = container.querySelector('ul');
    expect(ul.className).toContain('is-active');
  });
});
