const nextJest = require('next/jest.js')

const createJestConfig = nextJest({ dir: './' })

const config = {
  testEnvironment: 'jsdom',
  testPathIgnorePatterns: [
    '<rootDir>/.next/',
    '<rootDir>/node_modules/',
    '<rootDir>/e2e/',
  ],
}

module.exports = createJestConfig(config)
