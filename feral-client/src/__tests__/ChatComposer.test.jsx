import { render, screen, fireEvent } from '@testing-library/react';
import ChatComposer from '../components/chat/ChatComposer';

vi.mock('../components/VoiceWaveform', () => ({
  default: ({ mode }) => <div data-testid="waveform">{mode}</div>,
}));

const defaults = {
  inputText: '',
  setInputText: vi.fn(),
  isRecording: false,
  isThinking: false,
  isStreaming: false,
  cameraOn: false,
  currentThreadId: 'abc123',
  onSubmit: vi.fn(e => e.preventDefault()),
  onToggleRecording: vi.fn(),
  onToggleCamera: vi.fn(),
  onStartNewThread: vi.fn(),
};

describe('ChatComposer', () => {
  it('renders input field and send button', () => {
    render(<ChatComposer {...defaults} />);
    expect(screen.getByPlaceholderText('Message FERAL...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start new chat/i })).toBeInTheDocument();
  });

  it('fires onSubmit when form is submitted', () => {
    render(<ChatComposer {...defaults} inputText="hello" />);
    fireEvent.submit(screen.getByPlaceholderText('Message FERAL...').closest('form'));
    expect(defaults.onSubmit).toHaveBeenCalled();
  });

  it('calls setInputText on typing', () => {
    const setInputText = vi.fn();
    render(<ChatComposer {...defaults} setInputText={setInputText} />);
    fireEvent.change(screen.getByPlaceholderText('Message FERAL...'), { target: { value: 'hi' } });
    expect(setInputText).toHaveBeenCalledWith('hi');
  });

  it('renders camera toggle button', () => {
    render(<ChatComposer {...defaults} />);
    expect(screen.getByTitle('Start camera')).toBeInTheDocument();
  });

  it('renders recording toggle button', () => {
    render(<ChatComposer {...defaults} />);
    expect(screen.getByTitle('Start voice')).toBeInTheDocument();
  });

  it('shows waveform when recording', () => {
    render(<ChatComposer {...defaults} isRecording />);
    expect(screen.getByTestId('waveform')).toBeInTheDocument();
  });

  it('displays truncated thread id', () => {
    render(<ChatComposer {...defaults} currentThreadId="0123456789abcdef" />);
    expect(screen.getByText('thread:0123456789')).toBeInTheDocument();
  });
});
