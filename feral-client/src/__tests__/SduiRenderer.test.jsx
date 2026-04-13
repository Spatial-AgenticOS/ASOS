import { render, screen } from '@testing-library/react'
import { SduiRenderer } from '../components/SduiRenderer'

describe('SduiRenderer', () => {
  it('renders a Text node', () => {
    const node = { type: 'Text', value: 'Hello FERAL' }
    render(<SduiRenderer node={node} />)
    expect(screen.getByText('Hello FERAL')).toBeInTheDocument()
  })

  it('renders a VStack with children', () => {
    const node = {
      type: 'VStack',
      spacing: 8,
      children: [
        { type: 'Text', value: 'First child' },
        { type: 'Text', value: 'Second child' },
      ],
    }
    render(<SduiRenderer node={node} />)
    expect(screen.getByText('First child')).toBeInTheDocument()
    expect(screen.getByText('Second child')).toBeInTheDocument()
  })

  it('returns null for null node', () => {
    const { container } = render(<SduiRenderer node={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders a Badge with label', () => {
    const node = { type: 'Badge', label: 'New' }
    render(<SduiRenderer node={node} />)
    expect(screen.getByText('New')).toBeInTheDocument()
  })
})
