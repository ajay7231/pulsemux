import { createCallSimulator } from './call.js';
const selection = new URLSearchParams(location.search);
const selectedAgent = selection.get('agent');
try {
  let agent;
  if (selectedAgent) {
    const response = await fetch('/api/agents/' + encodeURIComponent(selectedAgent));
    if (!response.ok) throw new Error('Sign in and select an agent from the dashboard.');
    agent = await response.json();
  }
  const controller = createCallSimulator(document, {agent, draft: selection.get('draft') === '1'});
  Object.assign(window, controller, {updateConfig() {}});
  if (agent) document.getElementById('status-desc').textContent = 'Testing saved agent: ' + agent.name;
} catch (error) {
  document.getElementById('call-notice').textContent = error.message;
}
