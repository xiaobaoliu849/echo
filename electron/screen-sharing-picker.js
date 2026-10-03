window.echoScreenPicker.onSources(sources => {
  const container = document.getElementById('sources');
  for (const source of sources) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'source';
    button.title = source.name;
    const image = document.createElement('img');
    image.alt = '';
    if (source.thumbnail.startsWith('data:image/')) image.src = source.thumbnail;
    const name = document.createElement('span');
    name.textContent = source.name;
    button.append(image, name);
    button.addEventListener('click', () => window.echoScreenPicker.select(source.id));
    container.appendChild(button);
  }
  // Enter must not accidentally share a source.
  document.getElementById('cancel').focus();
});
document.getElementById('cancel').addEventListener('click', () => window.echoScreenPicker.select(null));
document.addEventListener('keydown', event => { if (event.key === 'Escape') window.echoScreenPicker.select(null); });
