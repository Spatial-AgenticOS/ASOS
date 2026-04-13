import { render, screen } from '@testing-library/react'
import ProactiveToast from '../components/ProactiveToast'

describe('ProactiveToast', () => {
  it('renders title and message', () => {
    const alert = {
      title: 'Heads up',
      message: 'Your heart rate is elevated',
      kind: 'warning',
    }
    render(<ProactiveToast alert={alert} />)
    expect(screen.getByText('Heads up')).toBeInTheDocument()
    expect(screen.getByText('Your heart rate is elevated')).toBeInTheDocument()
  })

  it('renders nothing when alert is null', () => {
    const { container } = render(<ProactiveToast alert={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders an action button when action_label is provided', () => {
    const alert = {
      title: 'Suggestion',
      message: 'Try a breathing exercise',
      kind: 'suggestion',
      action_label: 'Start now',
    }
    render(<ProactiveToast alert={alert} />)
    expect(screen.getByText('Start now')).toBeInTheDocument()
  })
})
