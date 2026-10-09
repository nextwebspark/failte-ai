export const HEADLESS_CHAT_EXAMPLE = `let chatState = 'idle';

function withFallchaWidget(callback) {
  if (window.FallchaWidget) {
    callback(window.FallchaWidget);
    return;
  }

  const script = document.getElementById('fallcha-widget');
  if (!script) {
    console.error('Fallcha.ai embed script not found');
    return;
  }

  script.addEventListener('load', () => {
    if (window.FallchaWidget) callback(window.FallchaWidget);
  }, { once: true });
}

withFallchaWidget((widget) => {
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
