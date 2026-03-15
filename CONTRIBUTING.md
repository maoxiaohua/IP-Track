# Contributing to IP-Track

We welcome contributions! Here's how you can help make IP-Track better.

## 🚀 Getting Started

1. **Fork the repository**
2. **Clone your fork**
   ```bash
   git clone https://github.com/yourusername/ip-track.git
   cd ip-track
   ```

3. **Set up development environment**
   - Follow the Development section in [README.md](README.md)
   - Install dependencies for both backend and frontend
   - Set up your `.env` file with test credentials

## 💻 Development Workflow

1. **Create a feature branch**
   ```bash
   git checkout -b feature/my-new-feature
   ```

2. **Make your changes**
   - Write clean, readable code
   - Follow existing code style
   - Add tests for new features
   - Update documentation as needed

3. **Test your changes**
   ```bash
   # Backend tests
   cd backend
   pytest

   # Frontend tests
   cd frontend
   npm run test
   ```

4. **Commit your changes**
   ```bash
   git add .
   git commit -m "Add: Brief description of your changes"
   ```

5. **Push to your fork**
   ```bash
   git push origin feature/my-new-feature
   ```

6. **Create a Pull Request**
   - Go to the original repository on GitHub
   - Click "New Pull Request"
   - Select your fork and branch
   - Fill in the PR template

## 📝 Code Style Guidelines

### Backend (Python)

- Follow [PEP 8](https://pep8.org/) style guide
- Use type hints for function parameters and return values
- Add docstrings to all functions and classes
- Keep functions focused and under 50 lines when possible
- Use meaningful variable names

**Example:**
```python
async def get_switch_by_id(db: AsyncSession, switch_id: int) -> Optional[Switch]:
    """
    Retrieve a switch by its ID.

    Args:
        db: Database session
        switch_id: ID of the switch to retrieve

    Returns:
        Switch object if found, None otherwise
    """
    result = await db.execute(
        select(Switch).where(Switch.id == switch_id)
    )
    return result.scalar_one_or_none()
```

### Frontend (TypeScript/Vue)

- Follow Vue 3 Composition API patterns
- Use TypeScript strictly (avoid `any` types)
- Format code with Prettier
- Use meaningful component and variable names
- Keep components focused on a single responsibility

**Example:**
```typescript
interface SwitchData {
  id: number
  name: string
  ipAddress: string
  vendor: string
}

const fetchSwitch = async (id: number): Promise<SwitchData | null> => {
  try {
    const response = await api.get(`/switches/${id}`)
    return response.data
  } catch (error) {
    console.error('Failed to fetch switch:', error)
    return null
  }
}
```

## 🧪 Testing

### Writing Tests

- Write unit tests for all new functions
- Write integration tests for API endpoints
- Ensure tests are independent and can run in any order
- Use descriptive test names

**Backend Test Example:**
```python
async def test_create_switch(db_session):
    """Test creating a new switch"""
    switch_data = {
        "name": "Test Switch",
        "ip_address": "192.168.1.1",
        "vendor": "cisco"
    }
    switch = await create_switch(db_session, switch_data)

    assert switch.name == "Test Switch"
    assert switch.ip_address == "192.168.1.1"
    assert switch.vendor == "cisco"
```

### Running Tests

```bash
# Backend - all tests
cd backend
pytest

# Backend - specific test file
pytest tests/test_switches.py

# Backend - with coverage
pytest --cov=src --cov-report=html

# Frontend - all tests
cd frontend
npm run test

# Frontend - watch mode
npm run test:watch
```

## 🐛 Reporting Bugs

When reporting bugs, please include:

1. **Description**: Clear description of the bug
2. **Steps to Reproduce**:
   - Step 1
   - Step 2
   - Step 3
3. **Expected Behavior**: What you expected to happen
4. **Actual Behavior**: What actually happened
5. **Environment**:
   - OS (Linux, macOS, Windows)
   - Docker version or Python/Node versions
   - Browser (for frontend issues)
6. **Logs**: Relevant error messages or logs
   ```bash
   docker logs iptrack-backend
   ```

## 💡 Feature Requests

We love new ideas! When requesting features:

1. **Use Case**: Describe the problem you're trying to solve
2. **Proposed Solution**: How you envision the feature working
3. **Alternatives**: Other approaches you've considered
4. **Additional Context**: Screenshots, mockups, or examples

## 🔍 Code Review Process

All submissions require review. We use GitHub pull requests for this purpose.

**Review Criteria:**
- Code quality and style
- Test coverage
- Documentation updates
- Performance impact
- Security considerations

**Timeline:**
- Initial review: Usually within 2-3 days
- Follow-up reviews: 1-2 days after updates

## 📚 Documentation

When adding new features, please update:

- **README.md**: If it affects installation or usage
- **Code Comments**: For complex logic
- **Docstrings**: For all new functions/classes
- **.env.example**: If adding new configuration variables

## 🌟 Good First Issues

Looking for somewhere to start? Check out issues labeled `good first issue`:
- Bug fixes
- Documentation improvements
- Small feature additions
- Test coverage improvements

## 🤝 Community Guidelines

- Be respectful and inclusive
- Provide constructive feedback
- Help others learn and grow
- Follow our [Code of Conduct](CODE_OF_CONDUCT.md)

## 📧 Questions?

- **GitHub Discussions**: For general questions
- **GitHub Issues**: For bug reports and feature requests
- **Pull Requests**: For code contributions

---

Thank you for contributing to IP-Track! 🎉
