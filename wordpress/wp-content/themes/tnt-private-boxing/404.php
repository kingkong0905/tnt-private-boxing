<?php
/**
 * 404 template.
 */
?>
<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo esc_html( wp_get_document_title() ); ?></title>
<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<main id="content" style="max-width:860px;margin:0 auto;padding:40px 16px;">
	<h1><?php esc_html_e( 'Page not found', 'tnt-private-boxing' ); ?></h1>
	<p><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php esc_html_e( 'Back to the homepage', 'tnt-private-boxing' ); ?></a></p>
</main>
<?php wp_footer(); ?>
</body>
</html>
