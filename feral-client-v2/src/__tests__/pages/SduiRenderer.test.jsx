import { describe, it, expect, vi } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import SduiRenderer, { applySduiPatches } from '../../ui/SduiRenderer';

describe('SduiRenderer — primitives', () => {
  it('renders VStack w/ nested Text + Button', () => {
    const tree = {
      type: 'VStack',
      children: [
        { type: 'Text', value: 'Hello' },
        { type: 'Button', label: 'Do it', action_id: 'do_it' },
      ],
    };
    const { getByText, getByTestId } = renderV2(<SduiRenderer tree={tree} />);
    expect(getByText('Hello')).toBeInTheDocument();
    expect(getByTestId('sdui-btn-do_it')).toBeInTheDocument();
  });

  it('Button onAction fires with action_id', () => {
    const onAction = vi.fn();
    const { getByTestId } = renderV2(
      <SduiRenderer
        tree={{ type: 'Button', label: 'Go', action_id: 'go' }}
        onAction={onAction}
      />,
    );
    fireEvent.click(getByTestId('sdui-btn-go'));
    expect(onAction).toHaveBeenCalledWith('go', undefined);
  });

  it('Row + Column render as HStack + VStack aliases', () => {
    const tree = {
      type: 'Row',
      children: [
        { type: 'Column', children: [{ type: 'Text', value: 'a' }] },
      ],
    };
    const { getByText } = renderV2(<SduiRenderer tree={tree} />);
    expect(getByText('a')).toBeInTheDocument();
  });

  it('List renders items + empty state', () => {
    const { getByText, rerender } = renderV2(
      <SduiRenderer
        tree={{
          type: 'List',
          items: [
            { type: 'Text', value: 'item-1' },
            { type: 'Text', value: 'item-2' },
          ],
        }}
      />,
    );
    expect(getByText('item-1')).toBeInTheDocument();
    expect(getByText('item-2')).toBeInTheDocument();

    const { getByText: getEmpty } = renderV2(
      <SduiRenderer
        tree={{ type: 'List', items: [], empty_title: 'No rows yet' }}
      />,
    );
    expect(getEmpty('No rows yet')).toBeInTheDocument();
  });

  it('Tabs show active body + tab clicks swap', () => {
    const tree = {
      type: 'Tabs',
      items: [
        { id: 'a', label: 'A', body: { type: 'Text', value: 'body A' } },
        { id: 'b', label: 'B', body: { type: 'Text', value: 'body B' } },
      ],
      default_tab: 'a',
    };
    const { getByText, getByRole } = renderV2(<SduiRenderer tree={tree} />);
    expect(getByText('body A')).toBeInTheDocument();
    fireEvent.click(getByRole('tab', { name: 'B' }));
    expect(getByText('body B')).toBeInTheDocument();
  });

  it('Modal only renders when open', () => {
    const closed = renderV2(
      <SduiRenderer
        tree={{ type: 'Modal', open: false, body: { type: 'Text', value: 'hidden' } }}
      />,
    );
    expect(closed.queryByText('hidden')).toBeNull();

    const opened = renderV2(
      <SduiRenderer
        tree={{ type: 'Modal', open: true, title: 'Confirm?', body: { type: 'Text', value: 'visible' } }}
      />,
    );
    expect(opened.getByText('visible')).toBeInTheDocument();
    expect(opened.getByText('Confirm?')).toBeInTheDocument();
  });

  it('Checkbox passes boolean to onAction', () => {
    const onAction = vi.fn();
    const { getByRole } = renderV2(
      <SduiRenderer
        tree={{ type: 'Checkbox', label: 'opt', action_id: 'toggle' }}
        onAction={onAction}
      />,
    );
    fireEvent.click(getByRole('checkbox'));
    expect(onAction).toHaveBeenCalledWith('toggle', true);
  });

  it('Unknown type renders a visible unknown-component marker', () => {
    const { getByText } = renderV2(
      <SduiRenderer tree={{ type: 'Bogus-Widget' }} />,
    );
    expect(getByText(/Unknown SDUI component: Bogus-Widget/)).toBeInTheDocument();
  });
});

describe('SduiRenderer — Form values', () => {
  it('submit passes {values} object to onAction', () => {
    const onAction = vi.fn();
    const tree = {
      type: 'Form',
      action_id: 'send',
      submit_label: 'Send',
      fields: [
        { name: 'text', type: 'text', label: 'Message', value: '' },
        { name: 'urgent', type: 'checkbox', label: 'Urgent' },
      ],
    };
    const { getByTestId } = renderV2(<SduiRenderer tree={tree} onAction={onAction} />);
    const input = getByTestId('sdui-form-field-text');
    fireEvent.change(input, { target: { value: 'hello world' } });
    fireEvent.click(getByTestId('sdui-form-submit-send'));
    expect(onAction).toHaveBeenCalledWith('send', { values: { text: 'hello world', urgent: false } });
  });
});

describe('applySduiPatches', () => {
  it('replace rewrites a nested value', () => {
    const tree = { type: 'VStack', children: [{ type: 'Text', value: 'old' }] };
    const next = applySduiPatches(tree, [
      { path: 'children/0/value', op: 'replace', value: 'new' },
    ]);
    expect(next.children[0].value).toBe('new');
    // Input is untouched (immutable)
    expect(tree.children[0].value).toBe('old');
  });

  it('add to an array appends or inserts', () => {
    const tree = { type: 'VStack', children: [{ type: 'Text', value: 'a' }] };
    const next = applySduiPatches(tree, [
      { path: 'children/-', op: 'add', value: { type: 'Text', value: 'b' } },
    ]);
    expect(next.children).toHaveLength(2);
    expect(next.children[1].value).toBe('b');
  });

  it('remove drops an array element', () => {
    const tree = {
      type: 'VStack',
      children: [
        { type: 'Text', value: 'a' },
        { type: 'Text', value: 'b' },
      ],
    };
    const next = applySduiPatches(tree, [{ path: 'children/0', op: 'remove' }]);
    expect(next.children).toHaveLength(1);
    expect(next.children[0].value).toBe('b');
  });

  it('ignores bad paths without blowing up', () => {
    const tree = { type: 'Text', value: 'x' };
    const next = applySduiPatches(tree, [{ path: 'does/not/exist', op: 'replace', value: 'nope' }]);
    expect(next.value).toBe('x');
  });
});

// Phase 6 (permission_card) + Phase 11 (tcc_card) cards.
describe('SduiRenderer — permission_card / tcc_card', () => {
  it('renders permission_card with iOS deeplink button', () => {
    const tree = {
      type: 'permission_card',
      permission_key: 'NSContactsUsageDescription',
      title: 'FERAL needs access to Contacts',
      description: 'Looking up John requires Contacts access.',
      ios_deeplink: 'app-settings:',
      ios_deeplink_label: 'Open Settings',
      skill_id: 'contacts',
      action: 'phone.contact.lookup',
      retryable: true,
    };
    const { getByText } = renderV2(<SduiRenderer tree={tree} />);
    expect(getByText('FERAL needs access to Contacts')).toBeInTheDocument();
    expect(getByText('Looking up John requires Contacts access.')).toBeInTheDocument();
    expect(getByText('Open Settings')).toBeInTheDocument();
    expect(getByText('NSContactsUsageDescription')).toBeInTheDocument();
  });

  it('renders tcc_card with macOS surface label', () => {
    const tree = {
      type: 'tcc_card',
      permission_key: 'automation:com.apple.FaceTime',
      title: 'FERAL needs Automation access to FaceTime',
      description: 'macOS asks per-target permission to script FaceTime.',
      macos_deeplink: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation',
      macos_deeplink_label: 'Open System Settings',
      skill_id: 'desktop_facetime',
      action: 'desktop.facetime.start',
      retryable: true,
    };
    const { getByText } = renderV2(<SduiRenderer tree={tree} />);
    expect(getByText('FERAL needs Automation access to FaceTime')).toBeInTheDocument();
    expect(getByText('Open System Settings')).toBeInTheDocument();
    expect(getByText('automation:com.apple.FaceTime')).toBeInTheDocument();
  });

  it('falls back gracefully when deeplink is missing', () => {
    const tree = {
      type: 'permission_card',
      title: 'FERAL needs a permission',
      description: 'no deeplink',
      ios_deeplink: '',
      ios_deeplink_label: 'Open Settings',
    };
    // No button, just the fallback label text — assert by counting.
    const { container } = renderV2(<SduiRenderer tree={tree} />);
    const buttons = container.querySelectorAll('button');
    expect(buttons.length).toBe(0);
  });
});
