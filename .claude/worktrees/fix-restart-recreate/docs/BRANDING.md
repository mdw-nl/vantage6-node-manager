# Medical Data Works Branding

This application uses the Medical Data Works corporate branding and design system.

## Brand Colors

The following colors are used throughout the application:

- **Primary Blue**: `#00adef` - Main brand color, used for primary buttons, links, and accents
- **Secondary Blue**: `#51bcda` - Used for secondary links and hover states
- **Text Gray**: `#66615b` - Primary text color for readability
- **Background Light**: `#f8f9fa` - Light background for cards and sections

## Logo

Two versions of the Medical Data Works logo are included:

- `static/img/mdw-logo.png` - Full logo with text (used in navbar)
- `static/img/mdw-icon.png` - Icon-only version (without text)

The logo is sourced from https://www.medicaldataworks.nl

## Typography

The application uses the default system font stack:
- Primary: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif

## CSS Architecture

### Main Theme File: `static/mdw-theme.css`

This file contains all MDW-specific styling:
- CSS custom properties for colors
- Navbar styling
- Button styles
- Card and table styling
- Badge styles
- Form elements
- Footer styling

### Additional Styling: `templates/base.html`

Component-specific styles that extend the theme are defined in the base template:
- Sidebar navigation
- Status badges
- Stats cards

## Components

### Navigation Bar
- White background with MDW logo
- Light navbar theme with gray text
- Active state uses primary blue
- Box shadow for depth

### Buttons
- Primary buttons use `#00adef`
- Hover states use darker `#0088bd`
- Outline variants available

### Cards
- Light border with subtle shadow
- Header with bottom border in primary color
- Hover effect for better interaction

### Tables
- Striped rows with light blue tint (`rgba(0, 173, 239, 0.05)`)
- Header with primary blue bottom border
- Gray text for readability

### Footer
- Dark gray background (`#66615b`)
- White text with links
- References Medical Data Works website

## Customization

To modify the brand colors, update the CSS custom properties in `static/mdw-theme.css`:

```css
:root {
    --mdw-primary: #00adef;
    --mdw-secondary: #51bcda;
    --mdw-text-gray: #66615b;
    /* ... other colors */
}
```

## Medical Data Works

Medical Data Works is dedicated to making research data accessible through FAIR (Findable, Accessible, Interoperable, Reusable) and distributed principles.

- Website: https://www.medicaldataworks.nl
- Focus: Personal Health Train implementation
- Mission: Research data made accessible

## Attribution

This application is developed for and branded by Medical Data Works B.V.
