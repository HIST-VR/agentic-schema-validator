# Agentic Structured Extraction & Schema Validator

Paste a messy invoice or resume. The app asks a model to fill a strict record, then checks that record against business rules. If a rule fails, the exact validation error goes back to the model for another try. Three corrections can follow the first attempt. You either get a record that passed, or a log of why it did not.

The default model is Gemini 3.5 Flash. The same loop also runs on OpenAI and on SpaceXAI (`grok-4.7`).

## The catch in the samples

The first instruction tells the model to copy the numbers and dates as printed. The validators do not accept a printed figure when the math or the dates disagree.

The sample invoice says the amount due is 540.00. The lines add up to 749.00. A faithful copy fails. The next attempt is told the printed total is wrong, and what the lines actually sum to.

The sample resume has a cut-off email beside a real one, and a years-of-experience number that does not match the jobs. Those fail the same way.

## What has to be true

An invoice needs at least one line. Quantity is above zero, the unit price is zero or more, and the currency is a three-letter code (`usd` is kept as `USD`). A due date, when the document has one, cannot fall before the issue date. The total has to equal the line amounts after each line is rounded to the cent.

A resume needs a properly formed email. That check does not look the address up. Each job ends on or after it starts, and a current job has no end date. There is at least one skill. The stated years of experience have to land within a year of the calendar span of the work history. Open jobs run through today.

Dates can be ISO (`2023-03-01`), a month and year (`March 2023`), or a US numeric date (`03/14/2026`). A month with no day becomes the first of that month.

## What you see

The page is two columns. On the left you pick the provider, the model, and the schema: Invoice Extraction or Resume Parsing. You can paste text, load the dirty sample, or drop in a `.txt` or `.md` file.

On the right, a passed invoice or resume shows up as a record, then as JSON you can download. Above that is the run, attempt by attempt: what the model returned, the validation error when it failed, and the correction sent back. Earlier runs stay on the page for the session. A key typed into the form is not written into that log.
