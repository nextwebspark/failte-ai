export const HEADLESS_CHAT_EXAMPLE = `let chatState = 'idle';

function withLightMoveWidget(callback) {
  if (window.LightMoveWidget) {
    callback(window.LightMoveWidget);
    return;
  }

  const script = document.getElementById('lightmove-widget');
  if (!script) {
    console.error('LightMove.ai embed script not found');
    return;
  }

  script.addEventListener('load', () => {
    if (window.LightMoveWidget) callback(window.LightMoveWidget);
  }, { once: true });
}

withLightMoveWidget((widget) => {
  widget.onChatStateChange((state) => {
    chatState = state; // idle | starting | ready | waiting | ended | expired | error
  });

  widget.onMessage((text, turn) => {
    appendAgentBubble(text); // render however you want
  });

  document.getElementById('open-chat').addEventListener('click', () => {
    widget.startChat();
  });

  document.getElementById('send-btn').addEventListener('click', async () => {
    const input = document.getElementById('chat-input');
    appendVisitorBubble(input.value);
    const transcript = await widget.sendMessage(input.value);
    if (transcript !== null) input.value = '';
  });

  document.getElementById('end-chat')?.addEventListener('click', async () => {
    await widget.endChat();
  });
});`;
