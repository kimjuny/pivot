import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReactElement } from 'react'

export const renderWithUser = (component: ReactElement) => {
  const user = userEvent.setup()
  return {
    user,
    ...render(component),
  }
}

export const clickButton = async (user: ReturnType<typeof userEvent.setup>, buttonText: string) => {
  const button = screen.getByRole('button', { name: buttonText })
  await user.click(button)
}

export const typeInInput = async (user: ReturnType<typeof userEvent.setup>, label: string, text: string) => {
  const input = screen.getByLabelText(label)
  await user.type(input, text)
}

export const typeInTextarea = async (user: ReturnType<typeof userEvent.setup>, placeholder: string, text: string) => {
  const textarea = screen.getByPlaceholderText(placeholder)
  await user.type(textarea, text)
}
