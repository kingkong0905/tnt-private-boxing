<?php
/**
 * Fallback template for any view that has no dedicated template.
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
<?php if ( have_posts() ) : ?>
	<?php while ( have_posts() ) : the_post(); ?>
		<article <?php post_class(); ?>>
			<h1><?php the_title(); ?></h1>
			<?php the_content(); ?>
		</article>
	<?php endwhile; ?>
<?php else : ?>
	<p><?php esc_html_e( 'Nothing found.', 'tnt-private-boxing' ); ?></p>
<?php endif; ?>
</main>
<?php wp_footer(); ?>
</body>
</html>
