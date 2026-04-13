import { render, screen } from '@testing-library/react';
import MessageList from '../components/chat/MessageList';

vi.mock('../components/SduiRenderer', () => ({
  SduiRenderer: ({ node }) => <div data-testid="sdui">{JSON.stringify(node)}</div>,
}));
vi.mock('../components/TheOrb', () => ({
  default: () => <span data-testid="orb" />,
}));
vi.mock('../components/chat/SkillProposalCard', () => ({
  default: () => <div data-testid="skill-card" />,
}));

const baseProps = {
  messages: [],
  isConnected: true,
  isStreaming: false,
  streamingText: '',
  isThinking: false,
  greeting: null,
  onQuickAction: vi.fn(),
  onUIAction: vi.fn(),
  onSkillDecision: vi.fn(),
  skillProposalBusy: '',
  messagesEndRef: { current: null },
};

describe('MessageList', () => {
  it('shows empty state when no messages', () => {
    render(<MessageList {...baseProps} />);
    expect(screen.getByText('Start briefing')).toBeInTheDocument();
    expect(screen.getByText('Check health')).toBeInTheDocument();
  });

  it('renders user messages', () => {
    const messages = [{ role: 'user', type: 'text', content: 'Hello there' }];
    render(<MessageList {...baseProps} messages={messages} />);
    expect(screen.getByText('Hello there')).toBeInTheDocument();
  });

  it('renders assistant messages', () => {
    const messages = [{ role: 'assistant', type: 'text', content: 'I can help' }];
    render(<MessageList {...baseProps} messages={messages} />);
    expect(screen.getByText('I can help')).toBeInTheDocument();
  });

  it('shows thinking indicator when isThinking and not streaming', () => {
    render(<MessageList {...baseProps} isThinking />);
    const dots = document.querySelectorAll('.thinking-dot');
    expect(dots.length).toBe(3);
  });

  it('shows streaming text with cursor', () => {
    render(<MessageList {...baseProps} isStreaming streamingText="Typing..." />);
    expect(screen.getByText('Typing...')).toBeInTheDocument();
  });

  it('renders system messages centered', () => {
    const messages = [{ role: 'system', type: 'text', content: 'Thread started' }];
    render(<MessageList {...baseProps} messages={messages} />);
    expect(screen.getByText('Thread started')).toBeInTheDocument();
  });

  it('shows custom greeting when provided', () => {
    render(<MessageList {...baseProps} greeting={{ greeting: 'Hey champ!' }} />);
    expect(screen.getByText('Hey champ!')).toBeInTheDocument();
  });
});
