/* Agency-wide time estimates, using only visitor-supplied planning inputs. */
(function () {
  const inputs = ['sworn-personnel', 'scheduling-hours', 'reducible-time'].map(id => document.getElementById(id));
  const button = document.getElementById('estimate-time');
  if (!button || inputs.some(input => !input)) return;
  const annualOutput = document.getElementById('annual-scheduling-hours');
  const recoveredOutput = document.getElementById('annual-recoverable-hours');
  const context = document.getElementById('time-estimate-context');
  const error = document.getElementById('time-estimate-error');
  const formatter = new Intl.NumberFormat('en-US', {maximumFractionDigits: 1});
  let attempted = false;

  function calculate(moveFocus) {
    attempted = true;
    let invalid = null;
    inputs.forEach(input => {
      const valid = input.checkValidity() && Number.isFinite(input.valueAsNumber);
      input.setAttribute('aria-invalid', String(!valid));
      input.classList.toggle('is-invalid', !valid);
      if (!valid && !invalid) invalid = input;
    });
    const [personnel, weeklyHours, reduciblePercent] = inputs.map(input => input.valueAsNumber);
    // Hours are agency-wide. Personnel count adds context and is never a workload multiplier.
    const annualHours = weeklyHours * 52;
    const recoveredHours = annualHours * (reduciblePercent / 100);
    if (!invalid && (!Number.isFinite(annualHours) || !Number.isFinite(recoveredHours))) {
      invalid = inputs[1];
      invalid.setAttribute('aria-invalid', 'true');
      invalid.classList.add('is-invalid');
    }
    if (invalid) {
      error.textContent = 'Enter a whole number of sworn personnel greater than zero, a valid nonnegative weekly hours total, and a reducible percentage from 0 to 100.';
      error.classList.remove('hidden');
      annualOutput.textContent = 'Not calculated';
      recoveredOutput.textContent = 'Not calculated';
      context.textContent = 'Review the inputs to calculate agency-wide annual hours.';
      if (moveFocus) invalid.focus();
      return;
    }
    error.textContent = '';
    error.classList.add('hidden');
    annualOutput.textContent = formatter.format(annualHours) + ' hours';
    recoveredOutput.textContent = formatter.format(recoveredHours) + ' hours';
    context.textContent = 'Agency-wide scheduling estimate for ' + formatter.format(personnel) + ' sworn personnel, using a 52-week year and your ' + formatter.format(reduciblePercent) + ' percent reduction assumption.';
  }
  button.addEventListener('click', () => calculate(true));
  inputs.forEach(input => input.addEventListener('input', () => {
    if (attempted) calculate(false);
  }));
})();
