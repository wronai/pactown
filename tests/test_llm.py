"""Tests for pactown LLM functionality."""

import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from pactown.cli import cli


class TestLLMStatus:
    """Tests for pactown llm status command."""
    
    def test_llm_status_without_lolm(self):
        """Test llm status when lolm is not installed."""
        runner = CliRunner()

        with patch('pactown.cli.get_llm_status', return_value={
            'lolm_installed': False,
            'is_available': False,
            'error': 'lolm library not available in this environment',
            'install': 'pip install -U pactown[llm]',
        }):
            result = runner.invoke(cli, ['llm', 'status'])

            assert result.exit_code == 0
            assert 'lolm library not available' in result.output
            assert 'pip install -U pactown[llm]' in result.output
    
    def test_llm_status_with_providers(self):
        """Test llm status with available providers."""
        runner = CliRunner()
        
        mock_status = {
            'is_available': True,
            'lolm_installed': True,
            'lolm_version': '0.1.6',
            'rotation_available': False,
            'available_providers': ['openrouter', 'groq'],
            'providers': {
                'openrouter': {
                    'status': 'available',
                    'model': 'anthropic/claude-3-haiku',
                    'priority': 10,
                    'health': {
                        'success_rate': 0.95,
                        'total_requests': 100,
                        'rate_limit_hits': 2,
                    }
                },
                'groq': {
                    'status': 'available',
                    'model': 'llama-3.1-8b-instant',
                    'priority': 20,
                    'health': {
                        'success_rate': 1.0,
                        'total_requests': 50,
                        'rate_limit_hits': 0,
                    }
                },
                'ollama': {
                    'status': 'unavailable',
                    'model': 'llama3.2',
                    'priority': 30,
                    'error': 'Connection refused'
                }
            }
        }
        
        with patch('pactown.cli.get_llm_status', return_value=mock_status):
            result = runner.invoke(cli, ['llm', 'status'])

            assert result.exit_code == 0
            assert 'openrouter' in result.output
            assert 'groq' in result.output
            assert 'anthropic/claude-3-haiku' in result.output
    
    def test_llm_status_no_providers_available(self):
        """Test llm status when no providers are configured."""
        runner = CliRunner()
        
        mock_status = {
            'is_available': False,
            'lolm_installed': True,
            'lolm_version': '0.1.6',
            'rotation_available': False,
            'available_providers': [],
            'providers': {}
        }

        with patch('pactown.cli.get_llm_status', return_value=mock_status):
            result = runner.invoke(cli, ['llm', 'status'])

            assert result.exit_code == 0
            assert 'No LLM providers available' in result.output


class TestLLMPriority:
    """Tests for pactown llm priority command."""
    
    def test_llm_priority_set_success(self):
        """Test setting provider priority successfully."""
        runner = CliRunner()
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.set_llm_priority', return_value=True) as mock_set:
                result = runner.invoke(cli, ['llm', 'priority', 'openrouter', '5'])
                
                assert result.exit_code == 0
                assert 'Set openrouter priority to 5' in result.output
                mock_set.assert_called_once_with('openrouter', 5)
    
    def test_llm_priority_set_failure(self):
        """Test setting priority for unknown provider."""
        runner = CliRunner()
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.set_llm_priority', return_value=False):
                result = runner.invoke(cli, ['llm', 'priority', 'unknown', '5'])
                
                assert result.exit_code == 0
                assert 'Failed to set priority' in result.output
    
    def test_llm_priority_without_lolm(self):
        """Test priority command when lolm not installed."""
        runner = CliRunner()

        with patch('pactown.cli.is_lolm_available', return_value=False):
            result = runner.invoke(cli, ['llm', 'priority', 'openrouter', '5'])

            assert result.exit_code == 0
            assert 'lolm library not installed' in result.output


class TestLLMReset:
    """Tests for pactown llm reset command."""
    
    def test_llm_reset_success(self):
        """Test resetting provider health successfully."""
        runner = CliRunner()
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.reset_llm_provider', return_value=True) as mock_reset:
                result = runner.invoke(cli, ['llm', 'reset', 'groq'])
                
                assert result.exit_code == 0
                assert 'Reset groq health metrics' in result.output
                mock_reset.assert_called_once_with('groq')
    
    def test_llm_reset_failure(self):
        """Test reset for unknown provider."""
        runner = CliRunner()
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.reset_llm_provider', return_value=False):
                result = runner.invoke(cli, ['llm', 'reset', 'unknown'])
                
                assert result.exit_code == 0
                assert 'Failed to reset' in result.output


class TestLLMTest:
    """Tests for pactown llm test command."""
    
    def test_llm_test_basic(self):
        """Test basic LLM generation test."""
        runner = CliRunner()
        
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Hello from Pactown!"
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.get_llm', return_value=mock_llm):
                result = runner.invoke(cli, ['llm', 'test'])
                
                assert result.exit_code == 0
                assert 'Hello from Pactown!' in result.output
    
    def test_llm_test_with_rotation(self):
        """Test LLM generation with rotation flag."""
        runner = CliRunner()
        
        mock_llm = MagicMock()
        mock_llm.generate_with_rotation.return_value = "Hello with rotation!"
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.get_llm', return_value=mock_llm):
                result = runner.invoke(cli, ['llm', 'test', '--rotation'])
                
                assert result.exit_code == 0
                mock_llm.generate_with_rotation.assert_called_once()
    
    def test_llm_test_with_provider(self):
        """Test LLM generation with specific provider."""
        runner = CliRunner()
        
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Hello from OpenRouter!"
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.get_llm', return_value=mock_llm):
                result = runner.invoke(cli, ['llm', 'test', '--provider', 'openrouter'])
                
                assert result.exit_code == 0
                mock_llm.generate.assert_called_once()
                call_kwargs = mock_llm.generate.call_args[1]
                assert call_kwargs['provider'] == 'openrouter'
    
    def test_llm_test_error(self):
        """Test LLM generation error handling."""
        runner = CliRunner()
        
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = Exception("API error: rate limited")
        
        with patch('pactown.cli.is_lolm_available', return_value=True):
            with patch('pactown.cli.get_llm', return_value=mock_llm):
                result = runner.invoke(cli, ['llm', 'test'])
                
                assert result.exit_code == 0
                assert 'Error' in result.output
                assert 'rate limited' in result.output


class TestLLMDoctor:
    """Tests for pactown llm doctor command."""

    def test_llm_doctor_outputs_environment_info(self):
        runner = CliRunner()

        with patch('pactown.llm.get_lolm_info', return_value={
            'lolm_installed': False,
            'lolm_version': None,
            'lolm_import_error': 'No module named lolm',
            'rotation_available': False,
            'rotation_import_error': None,
        }):
            with patch('subprocess.check_output', return_value='pip 25.0 from /x/y (python 3.13)\n'):
                result = runner.invoke(cli, ['llm', 'doctor'])

                assert result.exit_code == 0
                assert 'LLM Doctor' in result.output
                assert 'Python:' in result.output
                assert 'pip:' in result.output
                assert 'lolm' in result.output
                assert 'Rotation' in result.output
                assert "-m pip install -U 'pactown[llm]'" in result.output


class TestLLMModule:
    """Tests for pactown.llm module functions."""
    
    def test_is_lolm_available_false(self):
        """Test is_lolm_available when lolm not installed."""
        from pactown.llm import is_lolm_available

        with patch('pactown.llm.LOLM_AVAILABLE', False):
            assert is_lolm_available() is False
    
    def test_get_llm_status_without_lolm(self):
        """Test get_llm_status returns proper error when lolm unavailable."""
        with patch('pactown.llm.LOLM_AVAILABLE', False):
            from pactown.llm import get_llm_status
            
            status = get_llm_status()
            
            assert status['lolm_installed'] is False
            assert status['is_available'] is False
            assert 'error' in status
            assert 'install' in status


class TestPactownLLMClass:
    """Tests for PactownLLM class."""
    
    def test_pactown_llm_singleton(self):
        """Test PactownLLM singleton pattern."""
        with patch('pactown.llm.LOLM_AVAILABLE', True):
            with patch('pactown.llm.LLMManager') as MockManager:
                MockManager.return_value = MagicMock()
                
                from pactown.llm import PactownLLM, get_llm
                
                # Reset singleton
                PactownLLM._instance = None
                
                llm1 = get_llm()
                llm2 = get_llm()
                
                assert llm1 is llm2
    
    def test_pactown_llm_generate_with_rotation(self):
        """Test generate_with_rotation delegates to manager."""
        with patch('pactown.llm.LOLM_AVAILABLE', True):
            mock_manager = MagicMock()
            mock_manager.generate_with_rotation.return_value = "Test response"
            mock_manager.is_available = True
            
            with patch('pactown.llm.LLMManager', return_value=mock_manager):
                from pactown.llm import PactownLLM
                
                # Reset singleton
                PactownLLM._instance = None
                
                llm = PactownLLM()
                llm._initialized = True
                llm._manager = mock_manager
                
                result = llm.generate_with_rotation("Test prompt")
                
                assert result == "Test response"
                mock_manager.generate_with_rotation.assert_called_once()
